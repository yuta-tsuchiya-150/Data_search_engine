import os
import re
import json
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Depends, Request, Form, Response, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import engine, get_db, Base, SessionLocal
from app.models.schema import User, Category, Source, Event, Favorite, NotificationLog, KeywordAlert, SourceRequest
from app.auth import hash_password, verify_password, get_current_user_optional, get_current_user_required
from app.scraper.runner import ScraperRunner
from app.scraper.discovery import URLDiscoveryEngine
from app.notifier.email_service import EmailNotifier

from sqlalchemy import text

# データベース初期化
Base.metadata.create_all(bind=engine)
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE sources ADD COLUMN last_scraped_at DATETIME;"))
        conn.commit()
    except Exception:
        pass

app = FastAPI(title="DataSearchHub - 小学校お受験・進学塾データ検索エンジン")

# Jinja2 テンプレート
templates = Jinja2Templates(directory="app/templates")

# APScheduler スケジューラ定義
scheduler = AsyncIOScheduler()

async def scheduled_scraping_job():
    """定期自動巡回タスク"""
    print(f"[{datetime.now()}] Background scheduled scraping job started...")
    db = SessionLocal()
    try:
        new_events = await ScraperRunner.run_all_scrapers(db, respect_interval=True)
        if new_events:
            print(f"[{datetime.now()}] Found {len(new_events)} new events during scheduled run!")
            notifications_count = EmailNotifier.notify_users_for_new_events(new_events, db)
            print(f"[{datetime.now()}] Sent {notifications_count} email notifications.")
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    # 設定ファイルの読み込み
    db = SessionLocal()
    try:
        config_dir = os.path.abspath("configs")
        ScraperRunner.load_configs_from_directory(config_dir, db)
        
        # デモ用ユーザーの自動セットアップ (管理者権限)
        admin_user = db.query(User).filter(User.username == "demo_user").first()
        if not admin_user:
            admin_user = User(
                username="demo_user",
                email="user@example.com",
                hashed_password=hash_password("password123"),
                is_paid=True,
                is_admin=True
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)

            # 初期サンプルキーワードアラートの登録
            default_keywords = ["説明会", "補欠", "倍率", "願書配布"]
            for kw in default_keywords:
                db.add(KeywordAlert(user_id=admin_user.id, keyword=kw))
            db.commit()
        else:
            admin_user.is_admin = True
            db.commit()

        # DBが空（イベントが0件）の場合、初回の自動巡回収集を実行
        if db.query(Event).count() == 0:
            print(f"[{datetime.now()}] Fresh database detected. Running initial scraping job...")
            await ScraperRunner.run_all_scrapers(db)
    finally:
        db.close()

    # スケジューラの開始
    if not scheduler.running:
        scheduler.add_job(scheduled_scraping_job, 'interval', minutes=10)
        scheduler.start()


@app.on_event("shutdown")
def shutdown_event():
    if scheduler.running:
        scheduler.shutdown()

# --- HTTP ルート定義 ---

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request, db: Session = Depends(get_db)):
    """専用スマートホーム画面 (ランディングページ)"""
    user = get_current_user_optional(request, db)
    total_sources = db.query(Source).count()
    total_events = db.query(Event).count()
    recent_events = db.query(Event).join(Source).order_by(Event.created_at.desc()).limit(6).all()

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "user": user,
            "total_sources_count": total_sources,
            "total_events_count": total_events,
            "recent_events": recent_events
        }
    )

@app.get("/events", response_class=HTMLResponse)
@app.get("/search", response_class=HTMLResponse)
async def events_search_page(
    request: Request,
    q: Optional[str] = Query(None),
    category: Optional[str] = Query("elementary_school"),
    source_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """イベント一覧・条件絞り込み検索画面"""
    user = get_current_user_optional(request, db)
    categories = db.query(Category).all()
    sources = db.query(Source).all()
    
    # 検索クエリ構築
    query = db.query(Event).join(Source)

    if category and category != "all":
        current_cat = db.query(Category).filter(Category.category_id == category).first()
        if current_cat:
            query = query.filter(Source.category_id == current_cat.id)

    parsed_source_id = None
    if source_id and source_id.isdigit():
        parsed_source_id = int(source_id)
        query = query.filter(Event.source_id == parsed_source_id)

    if event_type and event_type != "all":
        query = query.filter(Source.type == event_type)

    if q:
        search_term = f"%{q}%"
        query = query.filter(
            or_(
                Event.title.like(search_term),
                Event.content.like(search_term),
                Event.location.like(search_term),
                Source.name.like(search_term)
            )
        )

    events = query.order_by(Event.created_at.desc()).all()

    favorite_source_ids = []
    user_alert_keywords = []
    if user:
        favorite_source_ids = [fav.source_id for fav in user.favorites]
        user_alert_keywords = [alert.keyword for alert in user.keyword_alerts]

    # アラートキーワードの一致判定 (ハイライト用)
    for event in events:
        matched = []
        event_text = f"{event.title} {event.content or ''}"
        for kw in user_alert_keywords:
            if kw and kw.lower() in event_text.lower():
                matched.append(kw)
        event.matched_alerts = matched

    return templates.TemplateResponse(
        request=request,
        name="events.html",
        context={
            "user": user,
            "categories": categories,
            "sources": sources,
            "current_category_id": category,
            "selected_source_id": parsed_source_id,
            "selected_event_type": event_type,
            "search_query": q or "",
            "events": events,
            "favorite_source_ids": favorite_source_ids,
            "user_alert_keywords": user_alert_keywords
        }
    )

@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(
    request: Request,
    favorite_only: bool = Query(False),
    db: Session = Depends(get_db)
):
    user = get_current_user_optional(request, db)
    sources = db.query(Source).all()
    return templates.TemplateResponse(
        request=request,
        name="calendar.html",
        context={
            "user": user,
            "sources": sources,
            "favorite_only": favorite_only
        }
    )

@app.get("/api/calendar-events")
async def get_all_calendar_events(
    request: Request,
    favorite_only: bool = Query(False),
    source_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    user = get_current_user_optional(request, db)
    query = db.query(Event).join(Source)

    if source_id and source_id.isdigit():
        query = query.filter(Event.source_id == int(source_id))

    if favorite_only and user:
        fav_ids = [f.source_id for f in user.favorites]
        query = query.filter(Event.source_id.in_(fav_ids))

    events = query.all()

    calendar_data = []
    for e in events:
        raw_date = e.event_date or e.published_date or ""
        clean_digits = re.sub(r'[^0-9]', '', raw_date)[:8]

        if len(clean_digits) == 8:
            iso_start = f"{clean_digits[:4]}-{clean_digits[4:6]}-{clean_digits[6:8]}"
            google_date = f"{clean_digits}/{clean_digits}"
        else:
            # 日付文字列から8桁の年月日が取得できない場合、イベント追加日時(created_at)でフォールバック表示
            if e.created_at:
                iso_start = e.created_at.strftime('%Y-%m-%d')
                clean_date = e.created_at.strftime('%Y%m%d')
                google_date = f"{clean_date}/{clean_date}"
            else:
                iso_start = datetime.now().strftime('%Y-%m-%d')
                google_date = ""

        # Google カレンダー追加用ダイレクトURL
        gcal_url = ""
        if google_date:
            from urllib.parse import quote
            gcal_title = quote(f"[{e.source.name}] {e.title}")
            gcal_details = quote(f"{e.content or ''}\n\n詳細URL: {e.official_url}")
            gcal_location = quote(e.location or "")
            gcal_url = f"https://www.google.com/calendar/render?action=TEMPLATE&text={gcal_title}&dates={google_date}&details={gcal_details}&location={gcal_location}"

        calendar_data.append({
            "id": str(e.id),
            "title": f"[{e.source.name}] {e.title}",
            "start": iso_start,
            "url": e.official_url,
            "official_url": e.official_url,
            "source_name": e.source.name,
            "raw_title": e.title,
            "content": e.content or "詳細情報はありません。",
            "event_date": e.event_date or "未定",
            "published_date": e.published_date or "-",
            "location": e.location or "未指定",
            "google_calendar_url": gcal_url,
            "event_id": e.id,
            "backgroundColor": "#1e1b4b" if e.source.type == "school" else "#047857",
            "borderColor": "#4338ca"
        })

    res = JSONResponse(calendar_data)
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    res.headers["Pragma"] = "no-cache"
    res.headers["Expires"] = "0"
    return res

# --- iCal (.ics) ファイル生成 API ---

def build_ical_content(events: list) -> str:
    """イベントリストから iCalendar (RFC 5545) 形式のテキストを生成"""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DataSearchHub//NONSGML Event Calendar//JA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:DataSearchHub イベントカレンダー"
    ]

    for e in events:
        start_date = e.event_date if e.event_date else e.published_date
        clean_date = re.sub(r'[^0-9]', '', start_date or '')[:8]
        if not clean_date or len(clean_date) < 8:
            clean_date = datetime.now().strftime('%Y%m%d')

        title = f"[{e.source.name}] {e.title}".replace("\n", " ")
        content = (e.content or "").replace("\n", "\\n")
        location = (e.location or "").replace("\n", " ")
        url = e.url or ""

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:event_{e.id}_{clean_date}@datasearchhub",
            f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;VALUE=DATE:{clean_date}",
            f"DTEND;VALUE=DATE:{clean_date}",
            f"SUMMARY:{title}",
            f"DESCRIPTION:{content} \\n\\n詳細: {url}",
            f"LOCATION:{location}",
            f"URL:{url}",
            "END:VEVENT"
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)

@app.get("/events/{event_id}/ical")
async def get_single_event_ical(event_id: str, db: Session = Depends(get_db)):
    """単一イベントの .ics ファイルダウンロード"""
    if not event_id or not event_id.isdigit():
        raise HTTPException(status_code=400, detail="有効なイベントIDが指定されていません")

    event = db.query(Event).filter(Event.id == int(event_id)).first()
    if not event:
        raise HTTPException(status_code=404, detail="イベントが見つかりません")

    ical_text = build_ical_content([event])
    filename = f"event_{event_id}.ics"
    return Response(
        content=ical_text,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/user-calendar-feed.ics")
async def get_user_calendar_feed_ical(request: Request, db: Session = Depends(get_db)):
    """ログイン中ユーザーのお気に入りイベントをまとめた .ics ファイルを一括ダウンロード"""
    user = get_current_user_optional(request, db)
    if user:
        fav_ids = [f.source_id for f in user.favorites]
        events = db.query(Event).filter(Event.source_id.in_(fav_ids)).all() if fav_ids else []
    else:
        events = db.query(Event).all()

    ical_text = build_ical_content(events)
    filename = "my_favorites_calendar.ics"
    return Response(
        content=ical_text,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

def extract_group_name(source_name: str) -> str:
    """ソース名から親の「学校・塾グループ名」を抽出 (例: '青山学院初等部 - お知らせ' -> '青山学院初等部')"""
    name = re.sub(r'\s*[\(\（].*?[\)\）]', '', source_name)  # カッコ表記の除去
    if ' - ' in name:
        name = name.split(' - ')[0]
    return name.strip()

@app.get("/schools", response_class=HTMLResponse)
async def schools_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    sources = db.query(Source).all()
    
    user_fav_source_ids = set()
    if user:
        user_fav_source_ids = {fav.source_id for fav in user.favorites}

    # グループ化ロジック (学校・塾単位に集約)
    groups = {}
    for s in sources:
        gname = extract_group_name(s.name)
        if gname not in groups:
            groups[gname] = {
                "group_name": gname,
                "display_name": f"{gname}関係",
                "type": s.type,
                "sources": [],
                "total_events": 0,
                "is_fully_favorited": True,
                "is_partially_favorited": False
            }
        groups[gname]["sources"].append(s)
        groups[gname]["total_events"] += len(s.events)

    # 各グループのお気に入り状態を判定
    grouped_sources_list = []
    for gname, gdata in groups.items():
        source_ids = [s.id for s in gdata["sources"]]
        fav_count = sum(1 for sid in source_ids if sid in user_fav_source_ids)
        
        gdata["is_fully_favorited"] = (fav_count == len(source_ids)) and len(source_ids) > 0
        gdata["is_partially_favorited"] = (fav_count > 0) and not gdata["is_fully_favorited"]
        grouped_sources_list.append(gdata)

    return templates.TemplateResponse(
        request=request,
        name="schools.html",
        context={
            "user": user,
            "grouped_sources": grouped_sources_list
        }
    )

@app.post("/toggle-favorite-group")
async def toggle_favorite_group(request: Request, group_name: str = Form(...), db: Session = Depends(get_db)):
    """学校・塾グループ単位で全関連ソースを一括お気に入り追加/解除"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    sources = db.query(Source).all()
    matching_sources = [s for s in sources if extract_group_name(s.name) == group_name]
    matching_source_ids = [s.id for s in matching_sources]

    # 現在登録されているお気に入りを確認
    existing_favs = db.query(Favorite).filter(
        Favorite.user_id == user.id,
        Favorite.source_id.in_(matching_source_ids)
    ).all()

    if len(existing_favs) == len(matching_source_ids) and len(matching_source_ids) > 0:
        # すべて登録済みの場合は一括解除
        for fav in existing_favs:
            db.delete(fav)
    else:
        # 未登録分を一括追加
        existing_ids = {fav.source_id for fav in existing_favs}
        for sid in matching_source_ids:
            if sid not in existing_ids:
                db.add(Favorite(user_id=user.id, source_id=sid))
    
    db.commit()
    referer = request.headers.get("referer") or "/schools"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/toggle-favorite")
async def toggle_favorite(request: Request, source_id: int = Form(...), db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    fav = db.query(Favorite).filter(Favorite.user_id == user.id, Favorite.source_id == source_id).first()
    if fav:
        db.delete(fav)
    else:
        new_fav = Favorite(user_id=user.id, source_id=source_id)
        db.add(new_fav)
    db.commit()

    referer = request.headers.get("referer") or "/schools"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/keyword-alerts")
async def add_keyword_alert(
    request: Request,
    keyword: str = Form(...),
    db: Session = Depends(get_db)
):
    """キーワードアラートの追加"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    kw = keyword.strip()
    if kw:
        existing = db.query(KeywordAlert).filter(
            KeywordAlert.user_id == user.id,
            KeywordAlert.keyword == kw
        ).first()
        if not existing:
            db.add(KeywordAlert(user_id=user.id, keyword=kw))
            db.commit()

    referer = request.headers.get("referer") or "/dashboard"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/keyword-alerts/{alert_id}/delete")
async def delete_keyword_alert(
    request: Request,
    alert_id: int,
    db: Session = Depends(get_db)
):
    """キーワードアラートの削除"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    alert = db.query(KeywordAlert).filter(
        KeywordAlert.id == alert_id,
        KeywordAlert.user_id == user.id
    ).first()
    if alert:
        db.delete(alert)
        db.commit()

    referer = request.headers.get("referer") or "/dashboard"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    favorites = db.query(Favorite).filter(Favorite.user_id == user.id).all()
    fav_source_ids = [f.source_id for f in favorites]
    favorited_events = db.query(Event).filter(Event.source_id.in_(fav_source_ids)).order_by(Event.created_at.desc()).all() if fav_source_ids else []
    keyword_alerts = db.query(KeywordAlert).filter(KeywordAlert.user_id == user.id).all()

    # グループ化したお気に入りデータの計算
    fav_groups = {}
    for fav in favorites:
        gname = extract_group_name(fav.source.name)
        if gname not in fav_groups:
            fav_groups[gname] = {
                "group_name": gname,
                "display_name": f"{gname}関係",
                "sources_count": 0,
                "events_count": 0
            }
        fav_groups[gname]["sources_count"] += 1
        fav_groups[gname]["events_count"] += len(fav.source.events)

    grouped_favorites_list = list(fav_groups.values())

    grouped_favorites_list = list(fav_groups.values())

    user_requests = db.query(SourceRequest).filter(SourceRequest.user_id == user.id).order_by(SourceRequest.created_at.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "favorites": favorites,
            "grouped_favorites": grouped_favorites_list,
            "favorited_events": favorited_events,
            "keyword_alerts": keyword_alerts,
            "user_requests": user_requests
        }
    )

@app.post("/request-source")
async def request_source(
    request: Request,
    target_url: str = Form(...),
    note: Optional[str] = Form(""),
    db: Session = Depends(get_db)
):
    """一般ユーザーによる未登録学校・塾ページの追加リクエスト"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    url_clean = target_url.strip()
    if url_clean:
        new_req = SourceRequest(
            user_id=user.id,
            url=url_clean,
            note=note.strip() if note else "",
            status="pending"
        )
        db.add(new_req)
        db.commit()

    referer = request.headers.get("referer") or "/dashboard"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/scrape-now")
async def scrape_now(request: Request, source_id: int = Form(None), db: Session = Depends(get_db)):
    """即時スクレイピング手動実行"""
    if source_id:
        source = db.query(Source).filter(Source.id == source_id).first()
        if source:
            new_events = await ScraperRunner.run_scrape_for_source(source, db)
            sources_count = 1
        else:
            new_events = []
            sources_count = 0
    else:
        sources = db.query(Source).all()
        sources_count = len(sources)
        new_events = await ScraperRunner.run_all_scrapers(db)

    if new_events:
        notifications_sent = EmailNotifier.notify_users_for_new_events(new_events, db)
        print(f"Immediate scrape done: {len(new_events)} new events, {notifications_sent} notifications sent.")

    referer = request.headers.get("referer") or "/"
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(referer)
    qs = parse_qs(parsed.query)
    qs['scraped'] = ['true']
    qs['count'] = [str(len(new_events))]
    qs['sources'] = [str(sources_count)]
    new_query = urlencode(qs, doseq=True)
    redirect_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    categories = db.query(Category).all()
    sources = db.query(Source).all()
    notification_logs = db.query(NotificationLog).order_by(NotificationLog.sent_at.desc()).all()
    pending_requests = db.query(SourceRequest).order_by(SourceRequest.created_at.desc()).all()

    sources_with_json = []
    for s in sources:
        try:
            parsed_selectors = json.loads(s.selectors_json)
            formatted_json = json.dumps(parsed_selectors, ensure_ascii=False, indent=2)
        except Exception:
            formatted_json = s.selectors_json
        sources_with_json.append({
            "source": s,
            "formatted_selectors": formatted_json
        })

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "user": user,
            "categories": categories,
            "sources_with_json": sources_with_json,
            "notification_logs": notification_logs,
            "pending_requests": pending_requests
        }
    )

@app.post("/admin/update-request-status")
async def update_request_status(
    request: Request,
    request_id: int = Form(...),
    status_val: str = Form(...),
    db: Session = Depends(get_db)
):
    """管理者がユーザーからの追加リクエストステータス（approved/rejected/pending）を更新"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    req_obj = db.query(SourceRequest).filter(SourceRequest.id == request_id).first()
    if req_obj:
        req_obj.status = status_val
        db.commit()

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/discover-sources")
async def discover_sources(
    target_url: str = Form(...),
    school_name: Optional[str] = Form(""),
    limit: int = Form(10),
    db: Session = Depends(get_db)
):
    """URLから関連ページおよび学校名を自動検出・選別 (5~30件可変対応)"""
    results = await URLDiscoveryEngine.discover_relevant_urls(target_url, school_name or "", limit=limit)
    return JSONResponse({"status": "ok", "results": results})

@app.post("/admin/update-source-interval")
async def update_source_interval(
    request: Request,
    source_id: int = Form(...),
    schedule_interval_minutes: int = Form(...),
    db: Session = Depends(get_db)
):
    """登録ソースの巡回時間設定（分間隔）を可変更新"""
    source = db.query(Source).filter(Source.id == source_id).first()
    if source:
        source.schedule_interval_minutes = max(1, schedule_interval_minutes)
        db.commit()

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/delete-source")
async def delete_source(
    request: Request,
    source_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """登録されている巡回ソースを削除（解除）"""
    source = db.query(Source).filter(Source.id == source_id).first()
    if source:
        db.delete(source)
        db.commit()

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/add-discovered-source")
async def add_discovered_source(
    school_name: str = Form(...),
    source_url: str = Form(...),
    category_id: str = Form("elementary_school"),
    source_type: str = Form("school"),
    selectors_json: str = Form(...),
    db: Session = Depends(get_db)
):
    """選別されたソースをDBおよびYAML設定ファイルに自動追記登録"""
    cat = db.query(Category).filter(Category.category_id == category_id).first()
    if not cat:
        cat = Category(category_id=category_id, name="小学校お受験情報", description="自動生成カテゴリ")
        db.add(cat)
        db.commit()
        db.refresh(cat)

    source_id = "src_" + re.sub(r'[^a-zA-Z0-9_]', '', school_name.lower())[:15] + "_" + str(int(datetime.now().timestamp()))[-4:]

    new_source = Source(
        source_id=source_id,
        category_id=cat.id,
        name=school_name,
        type=source_type,
        url=source_url,
        schedule_interval_minutes=60,
        selectors_json=selectors_json
    )
    db.add(new_source)
    db.commit()
    db.refresh(new_source)

    await ScraperRunner.run_scrape_for_source(new_source, db)

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/add-all-discovered-sources")
async def add_all_discovered_sources(
    sources_json: str = Form(...),
    db: Session = Depends(get_db)
):
    """検出された全候補ソースを一括でまとめてDB登録＆即時巡回"""
    try:
        items = json.loads(sources_json)
    except Exception:
        return JSONResponse({"status": "error", "message": "JSONパースエラー"}, status_code=400)

    cat = db.query(Category).filter(Category.category_id == "elementary_school").first()
    if not cat:
        cat = Category(category_id="elementary_school", name="小学校お受験情報", description="自動生成カテゴリ")
        db.add(cat)
        db.commit()
        db.refresh(cat)

    added_count = 0
    for idx, item in enumerate(items):
        school_name = f"{item.get('school_name', '')} - {item.get('page_title', '')}"
        source_url = item.get('url', '')
        selectors_json = json.dumps(item.get('selectors', {}), ensure_ascii=False)
        
        # 重複登録チェック
        existing = db.query(Source).filter(Source.url == source_url).first()
        if existing:
            continue

        source_id = "src_" + re.sub(r'[^a-zA-Z0-9_]', '', school_name.lower())[:12] + f"_{idx}_" + str(int(datetime.now().timestamp()))[-4:]

        new_source = Source(
            source_id=source_id,
            category_id=cat.id,
            name=school_name,
            type="school",
            url=source_url,
            schedule_interval_minutes=60,
            selectors_json=selectors_json
        )
        db.add(new_source)
        db.commit()
        db.refresh(new_source)
        
        await ScraperRunner.run_scrape_for_source(new_source, db)
        added_count += 1

    return JSONResponse({"status": "ok", "added_count": added_count})

# --- ユーザー認証ルート ---

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, response: Response, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "ユーザー名またはパスワードが正しくありません"}
        )

    res = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    res.set_cookie(key="current_user", value=user.username, httponly=True)
    return res

@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")

@app.post("/register", response_class=HTMLResponse)
async def register_post(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    existing = db.query(User).filter((User.username == username) | (User.email == email)).first()
    if existing:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "このユーザー名またはメールアドレスは既に登録されています"}
        )

    new_user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_paid=True
    )
    db.add(new_user)
    db.commit()

    res = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    res.set_cookie(key="current_user", value=new_user.username, httponly=True)
    return res

@app.get("/logout")
async def logout():
    res = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    res.delete_cookie("current_user")
    return res
