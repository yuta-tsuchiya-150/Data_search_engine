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
from app.models.schema import User, Category, Source, Event, Favorite, NotificationLog
from app.auth import hash_password, verify_password, get_current_user_optional, get_current_user_required
from app.scraper.runner import ScraperRunner
from app.scraper.discovery import URLDiscoveryEngine
from app.notifier.email_service import EmailNotifier

# データベース初期化
Base.metadata.create_all(bind=engine)

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
        new_events = await ScraperRunner.run_all_scrapers(db)
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
        
        # デモ用ユーザーの自動セットアップ
        admin_user = db.query(User).filter(User.username == "demo_user").first()
        if not admin_user:
            demo_user = User(
                username="demo_user",
                email="user@example.com",
                hashed_password=hash_password("password123"),
                is_paid=True
            )
            db.add(demo_user)
            db.commit()
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
async def home(
    request: Request,
    q: Optional[str] = Query(None),
    category: Optional[str] = Query("elementary_school"),
    source_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
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
    if user:
        favorite_source_ids = [fav.source_id for fav in user.favorites]

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "categories": categories,
            "sources": sources,
            "current_category_id": category,
            "selected_source_id": parsed_source_id,
            "selected_event_type": event_type,
            "search_query": q or "",
            "events": events,
            "favorite_source_ids": favorite_source_ids
        }
    )

@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    sources = db.query(Source).all()
    return templates.TemplateResponse(
        request=request,
        name="calendar.html",
        context={
            "user": user,
            "sources": sources
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
        start_date = e.event_date if e.event_date else e.published_date
        if not start_date:
            continue
            
        calendar_data.append({
            "id": e.id,
            "title": f"[{e.source.name}] {e.title}",
            "start": start_date,
            "url": e.url or "#",
            "source_name": e.source.name,
            "raw_title": e.title,
            "content": e.content or "詳細情報はありません。",
            "event_date": e.event_date or "未定",
            "published_date": e.published_date or "-",
            "location": e.location or "未指定",
            "backgroundColor": "#1e1b4b" if e.source.type == "school" else "#047857",
            "borderColor": "#4338ca"
        })

    return JSONResponse(calendar_data)

@app.get("/schools", response_class=HTMLResponse)
async def schools_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    sources = db.query(Source).all()
    favorite_source_ids = []
    if user:
        favorite_source_ids = [fav.source_id for fav in user.favorites]

    return templates.TemplateResponse(
        request=request,
        name="schools.html",
        context={
            "user": user,
            "sources": sources,
            "favorite_source_ids": favorite_source_ids
        }
    )

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

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    favorites = db.query(Favorite).filter(Favorite.user_id == user.id).all()
    fav_source_ids = [f.source_id for f in favorites]
    favorited_events = db.query(Event).filter(Event.source_id.in_(fav_source_ids)).order_by(Event.created_at.desc()).all() if fav_source_ids else []

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "favorites": favorites,
            "favorited_events": favorited_events
        }
    )

@app.post("/scrape-now")
async def scrape_now(request: Request, source_id: int = Form(None), db: Session = Depends(get_db)):
    """即時スクレイピング手動実行"""
    if source_id:
        source = db.query(Source).filter(Source.id == source_id).first()
        if source:
            new_events = await ScraperRunner.run_scrape_for_source(source, db)
        else:
            new_events = []
    else:
        new_events = await ScraperRunner.run_all_scrapers(db)

    if new_events:
        notifications_sent = EmailNotifier.notify_users_for_new_events(new_events, db)
        print(f"Immediate scrape done: {len(new_events)} new events, {notifications_sent} notifications sent.")

    referer = request.headers.get("referer") or "/"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    categories = db.query(Category).all()
    sources = db.query(Source).all()
    notification_logs = db.query(NotificationLog).order_by(NotificationLog.sent_at.desc()).all()

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
            "notification_logs": notification_logs
        }
    )

@app.post("/admin/discover-sources")
async def discover_sources(
    school_name: str = Form(...),
    target_url: str = Form(...),
    db: Session = Depends(get_db)
):
    """学校名・URLからお受験関連ページを自動検出・選別"""
    results = await URLDiscoveryEngine.discover_relevant_urls(target_url, school_name)
    return JSONResponse({"status": "ok", "results": results})

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
