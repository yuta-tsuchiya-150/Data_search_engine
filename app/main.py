import os
import re
import json
import urllib.parse
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Depends, Request, Form, Response, HTTPException, status, Query, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import engine, get_db, Base, SessionLocal
from app.models.schema import User, Category, Source, Event, Favorite, NotificationLog, KeywordAlert, SourceRequest, KnowledgeDocument, AISelfHealingLog, TrialHistory
from app.auth import hash_password, verify_password, get_current_user_optional, get_current_user_required
from app.scraper.runner import ScraperRunner
from app.scraper.discovery import URLDiscoveryEngine
from app.scraper.ai_agent import AISchoolScraperAgent
from app.notifier.email_service import EmailNotifier
from app.scraper.school_helper import clean_and_enhance_source_name, infer_school_name_from_url, extract_group_name
from app.ai_chat.ai_advisor import OjukenAIAdvisor
from app.ai_chat.gemini_files_manager import GeminiFilesManager
import stripe

STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "").strip()
FREE_REGISTRATION_CAMPAIGN = os.getenv("FREE_REGISTRATION_CAMPAIGN", "true").strip().lower() in ("true", "1", "yes")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

from sqlalchemy import text

# データベース初期化およびPostgreSQL/SQLite自動カラム拡張
Base.metadata.create_all(bind=engine)

def auto_migrate_db():
    """PostgreSQL (Render等) および SQLite の両環境で安全にカラムを追加・マイグレーション"""
    from sqlalchemy import inspect
    try:
        inspector = inspect(engine)
        
        # 1. sources テーブルの last_scraped_at カラム自動追加
        if "sources" in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns("sources")]
            if "last_scraped_at" not in columns:
                with engine.begin() as conn:
                    col_type = "TIMESTAMP" if engine.name == "postgresql" else "DATETIME"
                    conn.execute(text(f"ALTER TABLE sources ADD COLUMN last_scraped_at {col_type};"))
                print("Added 'last_scraped_at' column to 'sources' table.")

        # 2. events テーブルの user_id カラム自動追加
        if "events" in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns("events")]
            if "user_id" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE events ADD COLUMN user_id INTEGER;"))
                print("Added 'user_id' column to 'events' table.")

        # 3. users テーブルの is_active, withdrawn_at, stripe_* カラム自動追加
        if "users" in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns("users")]
            if "is_active" not in columns:
                with engine.begin() as conn:
                    default_val = "TRUE" if engine.name == "postgresql" else "1"
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT {default_val};"))
                print("Added 'is_active' column to 'users' table.")
            if "withdrawn_at" not in columns:
                with engine.begin() as conn:
                    col_type = "TIMESTAMP" if engine.name == "postgresql" else "DATETIME"
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN withdrawn_at {col_type};"))
                print("Added 'withdrawn_at' column to 'users' table.")
            if "stripe_customer_id" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR;"))
                print("Added 'stripe_customer_id' column to 'users' table.")
            if "stripe_subscription_id" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR;"))
                print("Added 'stripe_subscription_id' column to 'users' table.")
            if "subscription_status" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE users ADD COLUMN subscription_status VARCHAR DEFAULT 'inactive';"))
                print("Added 'subscription_status' column to 'users' table.")
    except Exception as e:
        print(f"Auto migration warning (handled): {e}")

auto_migrate_db()

app = FastAPI(title="DataSearchHub - 小学校お受験・進学塾データ検索エンジン")

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    # 静的アセット以外はブラウザおよびプロキシキャッシュを完全に無効化
    if not request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

from app.device_helper import is_mobile_device

# Jinja2 テンプレート
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["is_mobile_device"] = is_mobile_device
templates.env.globals["FREE_REGISTRATION_CAMPAIGN"] = FREE_REGISTRATION_CAMPAIGN

# APScheduler スケジューラ定義
scheduler = AsyncIOScheduler()
GLOBAL_SCRAPE_INTERVAL_MINUTES = 240  # 4時間おき (240分)

async def scheduled_scraping_job():
    """定期自動巡回タスク"""
    print(f"[{datetime.now()}] Background scheduled scraping job started (Interval: {GLOBAL_SCRAPE_INTERVAL_MINUTES} min)...")
    db = SessionLocal()
    try:
        new_events = await ScraperRunner.run_all_scrapers(db, respect_interval=True)

        # 東京・神奈川の本番学校・大手塾（理英会・こぐま会・立教・青山・早稲田・洗足等）の実データ巡回同期
        try:
            from app.scraper.real_school_scraper import sync_real_school_events
            ins, upd, real_new_events = sync_real_school_events(db)
            if real_new_events:
                new_events.extend(real_new_events)
                print(f"[{datetime.now()}] Real scraper fetched {ins} new events, updated {upd} existing events.")
        except Exception as real_err:
            print(f"[{datetime.now()}] Error in real school scraper during scheduled run: {real_err}")

        # スクラップ完了後、同一日・同一内容の重複イベントを自動統合・整理
        try:
            from app.scraper.event_dedup_service import EventDedupService
            dedup_res = EventDedupService.deduplicate_events(db)
            if dedup_res["deleted_events"] > 0:
                print(f"[{datetime.now()}] 🧹 Post-scrape dedup: merged {dedup_res['deleted_events']} duplicate events.")
        except Exception as dedup_err:
            print(f"[{datetime.now()}] Error during post-scrape dedup: {dedup_err}")

        if new_events:
            # 重複統合で削除されたインスタンスを除外し、現在DBに有効に存在する最新レコードのみを抽出
            valid_ids = [e.id for e in new_events if hasattr(e, "id") and e.id is not None]
            alive_new_events = []
            if valid_ids:
                alive_new_events = db.query(Event).filter(Event.id.in_(valid_ids)).all()

            if alive_new_events:
                print(f"[{datetime.now()}] Found {len(alive_new_events)} alive new events during scheduled run!")
                try:
                    notifications_count = EmailNotifier.notify_users_for_new_events(alive_new_events, db)
                    print(f"[{datetime.now()}] Sent {notifications_count} email notifications.")
                except Exception as notif_err:
                    print(f"[{datetime.now()}] Error sending user notifications: {notif_err}")

                try:
                    # マスター宛て新着回収ダイジェストレポートを送信
                    EmailNotifier.notify_admin_harvest_report(alive_new_events)
                except Exception as admin_err:
                    print(f"[{datetime.now()}] Error sending admin harvest report: {admin_err}")
    finally:
        db.close()

async def scheduled_dedup_job():
    """カレンダーおよびDB内の同一日・同一内容イベントの定期重複チェック＆統合タスク（30分間隔）"""
    print(f"[{datetime.now()}] 🧹 [PeriodicDedupJob] Checking calendar for duplicate events...")
    db = SessionLocal()
    try:
        from app.scraper.event_dedup_service import EventDedupService
        res = EventDedupService.deduplicate_events(db)
        if res["deleted_events"] > 0:
            print(f"[{datetime.now()}] 🧹 [PeriodicDedupJob] Successfully merged {res['deleted_events']} duplicate events across {res['merged_groups']} groups.")
        else:
            print(f"[{datetime.now()}] 🧹 [PeriodicDedupJob] No duplicate events found. Calendar is clean.")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ [PeriodicDedupJob] Error during duplicate check: {e}")
    finally:
        db.close()

async def scheduled_url_health_job():
    """イベント公式サイトリンクの死活監視・404検知および学校トップページ自動フォールバック定期タスク（60分間隔）"""
    print(f"[{datetime.now()}] 🔗 [URLHealthJob] Starting periodic URL health check...")
    db = SessionLocal()
    try:
        from app.scraper.url_health_service import URLHealthService
        res = await URLHealthService.check_and_repair_event_urls(db)
        if res["fixed"] > 0:
            print(f"[{datetime.now()}] 🔗 [URLHealthJob] Completed: Repaired {res['fixed']} broken URLs to school homepages (Total checked: {res['checked']}).")
        else:
            print(f"[{datetime.now()}] 🔗 [URLHealthJob] All {res['checked']} URLs are healthy.")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ [URLHealthJob] Error during URL health check: {e}")
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    # 設定ファイルの読み込み
    db = SessionLocal()
    try:
        config_dir = os.path.abspath("configs")
        ScraperRunner.load_configs_from_directory(config_dir, db)

        # マイ個人予定用ソースの確認と作成
        personal_source = db.query(Source).filter(Source.source_id == "my_personal_events").first()
        if not personal_source:
            cat = db.query(Category).first()
            if cat:
                personal_source = Source(
                    source_id="my_personal_events",
                    category_id=cat.id,
                    name="マイ個人予定",
                    type="personal",
                    url="https://example.com/personal",
                    selectors_json="{}"
                )
                db.add(personal_source)
                db.commit()
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

        # ナレッジドキュメントの初期サンプルデータの自動投入
        if db.query(KnowledgeDocument).count() == 0:
            default_knowledges = [
                KnowledgeDocument(
                    title="YouTube: 【合格願書】立教小学校・青山学院・慶應の志望理由書のポイント解説",
                    type="youtube",
                    source_url="https://www.youtube.com/watch?v=ojuken_sample1",
                    content="立教小学校や青山学院初等部などの伝統校では、建学の精神と家庭の教育方針の合致が最重要視されます。願書・志望理由書では単なる褒め言葉ではなく、家庭でのお手伝いや自然体験、親子の具体的なエピソードを盛り込むことが成功の鍵です。"
                ),
                KnowledgeDocument(
                    title="ドキュメント: 大手幼児教室（理英会・ジャック）模試の復習と活用ノウハウ",
                    type="document",
                    source_url="https://www.rieikai.com/guide/moshi",
                    content="理英会やジャック幼児教育研究所などの全統オープン模試や学校別模試では、順位や偏差値以上に『間違えた問題のパターン分析』が大切です。模試当日の帰宅後に親子で優しく振り返りを行い、ペーパーの未習熟分野や行動観察での指示理解不足を特定・克服しましょう。"
                ),
                KnowledgeDocument(
                    title="ガイド: 保護者面接およびお子様面接のマナーと注意点",
                    type="guide",
                    source_url="https://www.jac-youjikyouiku.com/interview",
                    content="面接では入室時の自然な笑顔と『失礼いたします』の挨拶が好印象を与えます。父親と母親で教育方針や家庭での役割分担に食い違いがないよう事前にすり合わせを行いましょう。お子様が質問された際は保護者が途中で口を挟まず、温かく見守る姿勢が評価されます。"
                )
            ]
            db.add_all(default_knowledges)
            db.commit()

        # データベース内の重複イベントを自動クリーンアップ＆1つに統合
        try:
            from app.scraper.event_dedup_service import EventDedupService
            dedup_init = EventDedupService.deduplicate_events(db)
            if dedup_init["deleted_events"] > 0:
                print(f"[{datetime.now()}] 🧹 Initial startup dedup: merged {dedup_init['deleted_events']} duplicate events.")
        except Exception as err:
            print(f"[{datetime.now()}] Error in initial dedup: {err}")

        # DBが空（イベントが0件）の場合、初回の自動巡回収集を実行
        if db.query(Event).count() == 0:
            print(f"[{datetime.now()}] Fresh database detected. Running initial scraping job...")
            await ScraperRunner.run_all_scrapers(db)
    finally:
        db.close()

    # スケジューラの開始
    if not scheduler.running:
        scheduler.add_job(scheduled_scraping_job, 'interval', minutes=GLOBAL_SCRAPE_INTERVAL_MINUTES, id='global_scrape_job', replace_existing=True)
        # 定期重複チェックタスク（30分おきに自動巡回・統合）
        scheduler.add_job(scheduled_dedup_job, 'interval', minutes=30, id='periodic_dedup_job', replace_existing=True)
        # 定期URL死活チェック＆学校公式トップページフォールバックタスク（60分おき）
        scheduler.add_job(scheduled_url_health_job, 'interval', minutes=60, id='url_health_job', replace_existing=True)
        scheduler.start()
    else:
        scheduler.add_job(scheduled_dedup_job, 'interval', minutes=30, id='periodic_dedup_job', replace_existing=True)
        scheduler.add_job(scheduled_url_health_job, 'interval', minutes=60, id='url_health_job', replace_existing=True)



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
    upcoming_events = count_upcoming_events(db)
    recent_events = db.query(Event).options(joinedload(Event.source)).order_by(Event.created_at.desc()).limit(6).all()

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "user": user,
            "total_sources_count": total_sources,
            "total_events_count": upcoming_events,
            "upcoming_events_count": upcoming_events,
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
    query = db.query(Event).options(joinedload(Event.source))


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

def extract_iso_date_from_event(e) -> tuple:
    """
    Eventの各フィールド (event_date, published_date, title, content) から
    日付 (YYYY-MM-DD) および Google Calendar用フォーマット (YYYYMMDD) を高精度に抽出する。
    日程情報を含まない固定案内ページ等は (None, None) を返し、カレンダーの特定日溢れを防止する。
    """
    # カレンダーの開催日としては、Eventの開催日(event_date)を最優先とし、
    # 次にタイトル(title)や本文(content)に含まれる明確な日程（〇月〇日等）を採用する。
    # ※published_date（情報取得日・登録日）を開催日として採用すると、
    # スクレイピング実行日（今日）にイベントが集中してしまうため、カレンダー判定候補から完全に除外する。
    candidates = [
        e.event_date or "",
        e.title or "",
        e.content or ""
    ]

    current_year = datetime.now().year

    for text in candidates:
        if not text:
            continue
        
        # 1. YYYY年MM月DD日 / YYYY/MM/DD / YYYY-MM-DD / YYYY.MM.DD (例: 2026年9月6日, 2026-10-18)
        m1 = re.search(r'(20\d{2})[\s年/\.\-]\s*(\d{1,2})[\s月/\.\-]\s*(\d{1,2})', text)
        if m1:
            try:
                y, m, d = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
                if 2020 <= y <= 2030 and 1 <= m <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{m:02d}-{d:02d}", f"{y:04d}{m:02d}{d:02d}"
            except ValueError:
                pass

        # 2. 令和X年M月D日 (例: 令和8年9月6日)
        m_reiwa = re.search(r'令和\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', text)
        if m_reiwa:
            try:
                r_year, m, d = int(m_reiwa.group(1)), int(m_reiwa.group(2)), int(m_reiwa.group(3))
                y = 2018 + r_year
                if 1 <= m <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{m:02d}-{d:02d}", f"{y:04d}{m:02d}{d:02d}"
            except ValueError:
                pass

        # 3. MM月DD日 / M月D日 (例: 9月6日, 10月18日)
        m2 = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日', text)
        if m2:
            try:
                m, d = int(m2.group(1)), int(m2.group(2))
                if 1 <= m <= 12 and 1 <= d <= 31:
                    return f"{current_year:04d}-{m:02d}-{d:02d}", f"{current_year:04d}{m:02d}{d:02d}"
            except ValueError:
                pass

        # 4. M/D または MM/DD (例: 9/6, 10/18)
        m3 = re.search(r'(?:^|[^\d])(\d{1,2})/(\d{1,2})(?:[^\d]|$)', text)
        if m3:
            try:
                m, d = int(m3.group(1)), int(m3.group(2))
                if 1 <= m <= 12 and 1 <= d <= 31:
                    return f"{current_year:04d}-{m:02d}-{d:02d}", f"{current_year:04d}{m:02d}{d:02d}"
            except ValueError:
                pass

    # 明確なスケジュール・日程が特定できない記事や固定ページはカレンダーに表示させない (None)
    return None, None

def classify_event_category(title: str, content: str = "", source_type: str = "school") -> dict:
    """
    イベントのタイトル・本文から「願書配布」「説明会」「入学試験」「合格発表」「模試」等を分類し、
    カレンダー用のバッジ表示、種別名、背景色、枠線色を返す
    """
    text = f"{title} {content}".lower()
    
    if any(kw in text for kw in ["願書", "要項", "出願", "受付", "申込", "web出願"]):
        return {
            "label": "願書・出願受付",
            "badge": "【願書・出願】",
            "bg": "#d97706",
            "border": "#b45309"
        }
    elif any(kw in text for kw in ["入試", "試験", "選考", "面接", "適性検査", "筆記"]):
        return {
            "label": "入学試験・面接",
            "badge": "【入学試験】",
            "bg": "#be123c",
            "border": "#9f1239"
        }
    elif any(kw in text for kw in ["合格", "発表", "手続", "入学手続"]):
        return {
            "label": "合格発表・手続",
            "badge": "【合格発表】",
            "bg": "#047857",
            "border": "#065f46"
        }
    elif source_type == "cram_school" or any(kw in text for kw in ["模試", "テスト", "判定", "講座", "講習"]):
        return {
            "label": "お受験模試・講習",
            "badge": "【模試・テスト】",
            "bg": "#0f766e",
            "border": "#115e59"
        }
    elif any(kw in text for kw in ["説明会", "見学", "オープンキャンパス", "公開授業", "ツアー", "体験", "イブニング"]):
        return {
            "label": "学校説明会・見学",
            "badge": "【学校説明会】",
            "bg": "#1e1b4b",
            "border": "#4338ca"
        }
    else:
        return {
            "label": "公式お知らせ",
            "badge": "【お知らせ】",
            "bg": "#334155",
            "border": "#1e293b"
        }

def clean_duplicate_events_in_db(db: Session) -> int:
    """DB内に多重登録されている重複イベント（同一source_id, タイトル, 開催日）を一括削除・整理"""
    events = db.query(Event).all()
    seen = {}
    deleted_count = 0
    for e in events:
        key = (e.source_id, (e.title or "").strip(), e.event_date or "", e.published_date or "")
        if key in seen:
            db.delete(e)
            deleted_count += 1
        else:
            seen[key] = e.id
    if deleted_count > 0:
        db.commit()
        print(f"[{datetime.now()}] Cleaned up {deleted_count} duplicate events in database.")
    return deleted_count

def count_upcoming_events(db: Session) -> int:
    """
    本日以降に開催予定の有効なイベント数を算出する。
    過去のイベント、日程の特定できない固定案内、テスト用サンプル、および重複イベントは除外される。
    """
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime("%Y-%m-%d")

    events = db.query(Event).options(joinedload(Event.source)).filter(Event.user_id == None).all()
    seen_keys = set()
    upcoming_count = 0

    for e in events:
        iso_start, clean_digits = extract_iso_date_from_event(e)
        if not iso_start or not clean_digits:
            continue
        if iso_start < today_str:
            continue

        # モック・ダミー・サンプル等の除外
        s_name = e.source.name if e.source else ""
        s_url = e.source.url if e.source else ""
        e_url = e.url or ""
        e_title = e.title or ""
        if any(term in s_name for term in ["その他校", "お気に入り校", "サンプル", "sample", "[Example]"]):
            continue
        if any(term in e_title for term in ["その他校", "お気に入り校", "サンプル", "sample", "[Example]"]):
            continue
        if any(term in s_url for term in ["127.0.0.1", "localhost", "example.com", "google.com/search"]):
            continue
        if any(term in e_url for term in ["127.0.0.1", "localhost", "example.com", "google.com/search"]):
            continue

        source_display_name = clean_and_enhance_source_name(e.source.name if e.source else "各種情報", e.source.url if e.source else "")
        core_school = re.sub(r'[\s\-・].*$', '', source_display_name).strip()
        from app.scraper.event_dedup_service import normalize_title_for_comparison
        norm_title = normalize_title_for_comparison(e.title, core_school)
        if not norm_title:
            norm_title = re.sub(r'\s+', '', e.title.strip().lower())

        dedup_key = f"{core_school}_{norm_title}_{iso_start}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        upcoming_count += 1

    return upcoming_count

@app.get("/api/calendar-events")
async def get_all_calendar_events(
    request: Request,
    favorite_only: bool = Query(False),
    source_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    user = get_current_user_optional(request, db)
    query = db.query(Event).options(joinedload(Event.source)).filter(Event.user_id == None)

    if source_id and source_id.isdigit():
        query = query.filter(Event.source_id == int(source_id))

    if favorite_only and user:
        fav_ids = [f.source_id for f in user.favorites]
        query = query.filter(Event.source_id.in_(fav_ids))

    events = query.all()

    # ユーザー個人の登録予定イベントも取得
    personal_events = []
    if user:
        personal_events = db.query(Event).options(joinedload(Event.source)).filter(Event.user_id == user.id).all()

    all_events = list(events) + list(personal_events)

    calendar_data = []
    seen_keys = set()

    for e in all_events:
        is_personal = (e.user_id is not None)
        iso_start, clean_digits = extract_iso_date_from_event(e)
        if not iso_start or not clean_digits:
            continue  # 具体的な開催日・公開日のない一般案内・固定ページはカレンダーから除外

        # モック・ダミー・Google検索URLを持つ不正イベントをカレンダーから徹底除外
        if not is_personal:
            s_name = e.source.name if e.source else ""
            s_url = e.source.url if e.source else ""
            e_url = e.url or ""
            e_title = e.title or ""
            if any(term in s_name for term in ["その他校", "お気に入り校", "サンプル", "sample", "[Example]"]):
                continue
            if any(term in e_title for term in ["その他校", "お気に入り校", "サンプル", "sample", "[Example]"]):
                continue
            if any(term in s_url for term in ["127.0.0.1", "localhost", "example.com", "google.com/search"]):
                continue
            if any(term in e_url for term in ["127.0.0.1", "localhost", "example.com", "google.com/search"]):
                continue

        source_display_name = "マイ個人予定" if is_personal else clean_and_enhance_source_name(e.source.name if e.source else "各種情報", e.source.url if e.source else "")
        core_school = re.sub(r'[\s\-・].*$', '', source_display_name).strip()
        from app.scraper.event_dedup_service import normalize_title_for_comparison
        norm_title = normalize_title_for_comparison(e.title, core_school)
        if not norm_title:
            norm_title = re.sub(r'\s+', '', e.title.strip().lower())
        
        # 同一日、同一学校、同一内容のイベントを完全に1つに集約する重複排除キー
        dedup_key = f"{e.user_id}_{core_school}_{norm_title}_{iso_start}" if not is_personal else f"{e.user_id}_{e.title.strip()}_{iso_start}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        google_date = f"{clean_digits}/{clean_digits}" if len(clean_digits) == 8 else ""
        category_info = classify_event_category(e.title, e.content or "", e.source.type if e.source else "school")

        # Google カレンダー追加用ダイレクトURL
        gcal_url = ""
        if google_date:
            from urllib.parse import quote
            gcal_title = quote(f"[{source_display_name}] {e.title}")
            gcal_details = quote(f"{e.content or ''}\n\n詳細URL: {e.official_url}")
            gcal_location = quote(e.location or "")
            gcal_url = f"https://www.google.com/calendar/render?action=TEMPLATE&text={gcal_title}&dates={google_date}&details={gcal_details}&location={gcal_location}"

        formatted_title = f"[マイ予定] 📌 {e.title}" if is_personal else f"[{source_display_name}] {category_info['badge']} {e.title}"
        bg_color = "#8b5cf6" if is_personal else category_info["bg"]
        border_color = "#7c3aed" if is_personal else category_info["border"]

        calendar_data.append({
            "id": str(e.id),
            "title": formatted_title,
            "start": iso_start,
            "url": e.official_url if not is_personal else "/calendar",
            "official_url": e.official_url if not is_personal else "/calendar",
            "source_name": source_display_name,
            "source_type": e.source.type if e.source else "personal",
            "source_type_label": "マイ個人予定" if is_personal else ("小学校・幼稚園" if e.source.type == "school" else "お受験進学塾"),
            "category_label": "マイ予定" if is_personal else category_info["label"],
            "category_badge": "【マイ予定】" if is_personal else category_info["badge"],
            "raw_title": e.title,
            "content": e.content or "詳細情報はありません。",
            "event_date": e.event_date or "未定",
            "published_date": e.published_date or "-",
            "location": e.location or "未指定",
            "google_calendar_url": gcal_url,
            "event_id": e.id,
            "backgroundColor": bg_color,
            "borderColor": border_color,
            "isPersonal": is_personal
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

        s_name = clean_and_enhance_source_name(e.source.name, e.source.url)
        title = f"[{s_name}] {e.title}".replace("\n", " ")
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



@app.get("/schools", response_class=HTMLResponse)
async def schools_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    sources = db.query(Source).options(joinedload(Source.events)).all()

    
    user_fav_source_ids = set()
    if user:
        user_fav_source_ids = {fav.source_id for fav in user.favorites}

    # グループ化ロジック (学校・塾単位に集約)
    groups = {}
    for s in sources:
        gname = extract_group_name(s.name, s.url)
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
    matching_sources = [s for s in sources if extract_group_name(s.name, s.url) == group_name]
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

    favorites = db.query(Favorite).options(joinedload(Favorite.source).joinedload(Source.events)).filter(Favorite.user_id == user.id).all()
    fav_source_ids = [f.source_id for f in favorites]
    favorited_events = db.query(Event).options(joinedload(Event.source)).filter(Event.source_id.in_(fav_source_ids)).order_by(Event.created_at.desc()).all() if fav_source_ids else []

    keyword_alerts = db.query(KeywordAlert).filter(KeywordAlert.user_id == user.id).all()

    # グループ化したお気に入りデータの計算
    fav_groups = {}
    for fav in favorites:
        gname = extract_group_name(fav.source.name, fav.source.url)
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

        # 東京・神奈川の実小学校・大手塾の本番データ同期
        try:
            from app.scraper.real_school_scraper import sync_real_school_events
            ins, upd, real_new_events = sync_real_school_events(db)
            if real_new_events:
                new_events.extend(real_new_events)
        except Exception as real_err:
            print(f"Error in real school scraper during immediate scrape: {real_err}")

        # スクラップ完了後、同一日・同一内容の重複イベントを自動統合
        try:
            from app.scraper.event_dedup_service import EventDedupService
            dedup_res = EventDedupService.deduplicate_events(db)
            if dedup_res["deleted_events"] > 0:
                print(f"🧹 Immediate scrape post-dedup: merged {dedup_res['deleted_events']} duplicate events.")
        except Exception as dedup_err:
            print(f"Error during post-scrape dedup: {dedup_err}")

    if new_events:
        notifications_sent = EmailNotifier.notify_users_for_new_events(new_events, db)
        print(f"Immediate scrape done: {len(new_events)} new events, {notifications_sent} notifications sent.")
        # マスター宛て新着回収ダイジェストレポートを送信
        EmailNotifier.notify_admin_harvest_report(new_events)

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

@app.post("/admin/sync-real-schools")
async def admin_sync_real_schools(request: Request, db: Session = Depends(get_db)):
    """東京・神奈川の主要小学校＆大手塾の実データ即時回収・同期エンドポイント"""
    try:
        from app.scraper.real_school_scraper import sync_real_school_events
        ins, upd, new_events = sync_real_school_events(db)
        
        # 収集後に重複イベントを自動統合
        from app.scraper.event_dedup_service import EventDedupService
        dedup_res = EventDedupService.deduplicate_events(db)
        
        # フォロー会員へ新着プッシュ通知およびマスターへダイジェストレポート
        notifications_count = 0
        if new_events:
            notifications_count = EmailNotifier.notify_users_for_new_events(new_events, db)
            EmailNotifier.notify_admin_harvest_report(new_events)

        msg = f"本番データ収集完了！新規: {ins}件（通知送信: {notifications_count}件）、更新: {upd}件（重複統合: {dedup_res['deleted_events']}件整理）"
    except Exception as e:
        msg = f"本番データ収集中にエラーが発生しました: {str(e)}"

    referer = request.headers.get("referer") or "/admin"
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(referer)
    qs = parse_qs(parsed.query)
    qs['msg'] = [msg]
    new_query = urlencode(qs, doseq=True)
    redirect_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/deduplicate-events")
async def admin_deduplicate_events(request: Request, db: Session = Depends(get_db)):
    """手動トリガー用：同一日・同一校・同一内容イベントの統合クリーンアップ"""
    try:
        from app.scraper.event_dedup_service import EventDedupService
        res = EventDedupService.deduplicate_events(db)
        msg = f"重複スケジュールの統合が完了しました！{res['merged_groups']}グループ・計 {res['deleted_events']} 件の重複を1つに統合しました。"
    except Exception as e:
        msg = f"重複統合処理中にエラーが発生しました: {str(e)}"

    referer = request.headers.get("referer") or "/admin"
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(referer)
    qs = parse_qs(parsed.query)
    qs['msg'] = [msg]
    new_query = urlencode(qs, doseq=True)
    redirect_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/check-url-health")
async def admin_check_url_health(request: Request, db: Session = Depends(get_db)):
    """手動トリガー用：全イベント公式サイトURL死活チェック＆学校トップページ自動フォールバック"""
    try:
        from app.scraper.url_health_service import URLHealthService
        res = await URLHealthService.check_and_repair_event_urls(db)
        msg = f"URL死活チェック完了！全 {res['checked']} 件中、{res['fixed']} 件のエラーURLを公式トップページへ自動修復しました。（正常: {res['alive']} 件）"
    except Exception as e:
        msg = f"URLチェック中にエラーが発生しました: {str(e)}"

    referer = request.headers.get("referer") or "/admin"
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(referer)
    qs = parse_qs(parsed.query)
    qs['msg'] = [msg]
    new_query = urlencode(qs, doseq=True)
    redirect_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

@app.get("/events/{event_id}/visit")
async def visit_event_official_site(event_id: int, db: Session = Depends(get_db)):
    """
    イベントの公式サイトリンクへ安全にリダイレクト。
    もしリンク先が404等のエラーで存在しない場合は、その学校・塾の公式トップページへ自動フォールバック転送する。
    """
    event = db.query(Event).options(joinedload(Event.source)).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url="/calendar", status_code=status.HTTP_303_SEE_OTHER)

    from app.scraper.url_health_service import URLHealthService
    fallback_url = URLHealthService.get_fallback_homepage(event)
    target_url = event.url or fallback_url

    # 無効なURLやローカルURL、Google検索URLの場合はフォールバックを試行
    if any(h in target_url for h in ["127.0.0.1", "localhost", "example.com", "google.com/search"]) or not target_url.startswith(("http://", "https://")):
        if fallback_url and fallback_url.startswith(("http://", "https://")) and not any(h in fallback_url for h in ["127.0.0.1", "localhost", "example.com", "google.com/search"]):
            return RedirectResponse(url=fallback_url, status_code=status.HTTP_302_FOUND)
        # 公式サイトURLが特定できない場合はGoogle検索等へ飛ばさず安全にカレンダーへ戻す
        return RedirectResponse(url="/calendar?msg=no_official_url", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)

@app.post("/admin/ai-scrape-url")
async def ai_scrape_url(
    target_url: str = Form(...),
    school_name: Optional[str] = Form(""),
    db: Session = Depends(get_db)
):
    """Gemini AIを活用し、指定された学校URLからイベント日程を自動抽出しSupabaseへ綺麗に登録"""
    clean_url = target_url.strip()
    if not clean_url:
        return JSONResponse({"status": "error", "message": "URLが入力されていません"}, status_code=400)

    result = await AISchoolScraperAgent.extract_and_register_events(clean_url, db, school_name=school_name or "")
    return JSONResponse(result)

@app.post("/admin/update-global-interval")
async def update_global_interval(
    request: Request,
    interval_minutes: int = Form(...),
    db: Session = Depends(get_db)
):
    """全体の定期自動巡回実行間隔（分）を画面から可変設定更新"""
    global GLOBAL_SCRAPE_INTERVAL_MINUTES
    new_interval = max(1, interval_minutes)
    GLOBAL_SCRAPE_INTERVAL_MINUTES = new_interval

    if scheduler.running:
        try:
            scheduler.reschedule_job('global_scrape_job', trigger='interval', minutes=new_interval)
        except Exception:
            scheduler.add_job(scheduled_scraping_job, 'interval', minutes=new_interval, id='global_scrape_job', replace_existing=True)

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    categories = db.query(Category).all()
    sources = db.query(Source).all()
    notification_logs = db.query(NotificationLog).order_by(NotificationLog.sent_at.desc()).all()
    healing_logs = db.query(AISelfHealingLog).order_by(AISelfHealingLog.created_at.desc()).limit(20).all()
    pending_requests = db.query(SourceRequest).order_by(SourceRequest.created_at.desc()).all()
    knowledge_docs = db.query(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).all()
    gemini_files = GeminiFilesManager.get_registered_files()

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

    all_users = db.query(User).order_by(User.id.asc()).all()
    active_users_count = sum(1 for u in all_users if getattr(u, "is_active", True) is not False)
    withdrawn_users_count = sum(1 for u in all_users if getattr(u, "is_active", True) is False)

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "user": user,
            "all_users": all_users,
            "active_users_count": active_users_count,
            "withdrawn_users_count": withdrawn_users_count,
            "categories": categories,
            "sources_with_json": sources_with_json,
            "notification_logs": notification_logs,
            "healing_logs": healing_logs,
            "pending_requests": pending_requests,
            "knowledge_docs": knowledge_docs,
            "gemini_files": gemini_files,
            "global_interval_minutes": GLOBAL_SCRAPE_INTERVAL_MINUTES,
            "smtp_config": EmailNotifier.get_smtp_config()
        }
    )

@app.post("/admin/send-test-email")
async def send_test_email_endpoint(
    request: Request,
    target_email: str = Form(...),
    db: Session = Depends(get_db)
):
    """管理画面からのテストメール即時送信"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    success = EmailNotifier.send_test_email(target_email.strip())
    referer = request.headers.get("referer") or "/admin"
    separator = "&" if "?" in referer else "?"
    status_flag = "success" if success else "failed"
    return RedirectResponse(url=f"{referer}{separator}test_email={status_flag}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/self-healing/trigger")
async def trigger_self_healing_manually(
    request: Request,
    source_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """管理者が対象ソースのAI自己修復を手動で即時テスト実行"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="指定のソースが見つかりません")

    try:
        import httpx
        from app.scraper.self_healing_agent import AISelfHealingAgent

        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            resp = await client.get(source.url)
            html_text = resp.text

        await AISelfHealingAgent.attempt_heal_source(
            source=source,
            html_content=html_text,
            db=db,
            reason="管理者画面からの手動AI自己修復テスト"
        )
    except Exception as e:
        print(f"Manual self-healing trigger error: {e}")

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/upload-gemini-file")
async def upload_gemini_file(
    request: Request,
    file: UploadFile = File(...),
    display_name: Optional[str] = Form(""),
    db: Session = Depends(get_db)
):
    """管理者から送られた画像・資料ファイルを Google Gemini AI サーバーへ直接アップロード"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    file_bytes = await file.read()
    filename = file.filename or "uploaded_file"
    mime_type = file.content_type or "application/octet-stream"

    res = await GeminiFilesManager.upload_file_to_gemini(
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type,
        display_name=display_name.strip() if display_name else filename
    )

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/delete-gemini-file")
async def delete_gemini_file(
    request: Request,
    file_uri: str = Form(...),
    db: Session = Depends(get_db)
):
    """Google Gemini サーバー上に保管されているファイルの登録解除"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    GeminiFilesManager.delete_registered_file(file_uri)
    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/api/ai-chat")
async def ai_chat_endpoint(
    request: Request,
    query: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """お受験AIサポートコンシェルジュへの質問回答・プリント画像OCR解析エンドポイント"""
    user = get_current_user_optional(request, db)

    image_bytes = None
    image_mime = None
    if image and image.filename:
        image_bytes = await image.read()
        image_mime = image.content_type or "image/jpeg"

    res = await OjukenAIAdvisor.answer_user_query(
        query=query or "",
        db=db,
        image_bytes=image_bytes,
        image_mime_type=image_mime
    )

    # ログインユーザーかつAIが予定イベント(単数または複数)を検出した場合、ユーザー個人イベントとして自動登録
    detected_events = res.get("detected_events") or []
    if not detected_events and res.get("detected_event"):
        detected_events = [res["detected_event"]]

    if user and detected_events:
        personal_src = db.query(Source).filter(Source.source_id == "my_personal_events").first()
        if not personal_src:
            cat = db.query(Category).first()
            personal_src = Source(
                source_id="my_personal_events",
                category_id=cat.id if cat else 1,
                name="マイ個人予定",
                type="personal",
                url="https://example.com/personal",
                selectors_json="{}"
            )
            db.add(personal_src)
            db.commit()
            db.refresh(personal_src)

        registered_events = []
        for det in detected_events:
            if not det.get("title") or not det.get("event_date"):
                continue

            # 重複チェック
            existing_personal = db.query(Event).filter(
                Event.user_id == user.id,
                Event.title == det["title"],
                Event.event_date == det["event_date"]
            ).first()

            if not existing_personal:
                new_personal_event = Event(
                    source_id=personal_src.id,
                    user_id=user.id,
                    title=det["title"],
                    content=det.get("content", ""),
                    event_date=det["event_date"],
                    location=det.get("location", "マイ個人予定")
                )
                db.add(new_personal_event)
                registered_events.append(det)

        if registered_events:
            db.commit()

            items_html = "".join([
                f'<li class="mt-1 flex items-start space-x-1.5"><span class="text-amber-500 font-bold">・</span><span><strong>{ev["event_date"]}</strong> : {ev["title"]} ({ev.get("location", "個別予定")})</span></li>'
                for ev in registered_events
            ])
            icon_badge = "📷 お便り・プリントから" if image_bytes else "📌 メッセージから"
            count_badge = f"{len(registered_events)} 件"

            notice_html = f"""
<div class="my-3 p-3.5 bg-gradient-to-br from-purple-50 to-indigo-50 border border-purple-200 rounded-2xl text-xs text-purple-950 shadow-sm">
    <div class="flex items-center space-x-2 font-bold text-purple-900 border-b border-purple-200/60 pb-2 mb-2">
        <i class="fa-solid fa-calendar-check text-purple-600 text-base"></i>
        <span>{icon_badge} {count_badge}の予定をマイカレンダーに自動登録しました！</span>
    </div>
    <ul class="text-slate-800 text-[11px] space-y-1">
        {items_html}
    </ul>
    <div class="mt-2.5 pt-2 border-t border-purple-200/40 flex items-center justify-between">
        <span class="text-[10px] text-purple-700">登録先: マイカレンダー</span>
        <a href="/calendar" class="font-bold text-purple-700 hover:text-purple-900 hover:underline flex items-center">
            カレンダーで確認する <i class="fa-solid fa-arrow-right ml-1 text-[10px]"></i>
        </a>
    </div>
</div>
"""
            res["answer"] = notice_html + res.get("answer", "")

    return JSONResponse(res)

@app.post("/admin/add-knowledge")
async def add_knowledge(
    request: Request,
    title: str = Form(...),
    type_val: str = Form("document"),
    source_url: Optional[str] = Form(""),
    content: str = Form(...),
    db: Session = Depends(get_db)
):
    """管理者がYouTube文字起こしや願書面接ドキュメントなどのAIナレッジを追加"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    if title.strip() and content.strip():
        new_doc = KnowledgeDocument(
            title=title.strip(),
            type=type_val,
            source_url=source_url.strip() if source_url else "",
            content=content.strip()
        )
        db.add(new_doc)
        db.commit()

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/delete-knowledge")
async def delete_knowledge(
    request: Request,
    doc_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """登録ナレッジの削除"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if doc:
        db.delete(doc)
        db.commit()

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)


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

@app.post("/admin/update-source-name")
async def update_source_name(
    request: Request,
    source_id: int = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db)
):
    """登録ソースの表示名称（Source.name）を管理者画面から直接変更・リネーム"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    source = db.query(Source).filter(Source.id == source_id).first()
    if source and name.strip():
        source.name = name.strip()
        db.commit()

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

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
    """登録されている巡回ソース（1項目）を削除（解除）"""
    source = db.query(Source).filter(Source.id == source_id).first()
    if source:
        # 関連イベントの通知ログ削除
        event_ids = [e.id for e in source.events]
        if event_ids:
            db.query(NotificationLog).filter(NotificationLog.event_id.in_(event_ids)).delete(synchronize_session=False)
            db.query(Event).filter(Event.source_id == source.id).delete(synchronize_session=False)
        db.query(Favorite).filter(Favorite.source_id == source.id).delete(synchronize_session=False)
        db.delete(source)
        db.commit()

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/delete-source-group")
async def delete_source_group(
    request: Request,
    group_name: str = Form(...),
    db: Session = Depends(get_db)
):
    """学校・塾グループ全体（例: 青山学院初等部関係、立教小学校など）に属する全ソース・イベントを一括解除・削除"""
    all_sources = db.query(Source).all()
    clean_target = group_name.strip()
    
    matching_sources = [
        s for s in all_sources
        if extract_group_name(s.name, s.url) == clean_target
        or s.name.startswith(clean_target)
        or clean_target in s.name
    ]

    for s in matching_sources:
        event_ids = [e.id for e in s.events]
        if event_ids:
            db.query(NotificationLog).filter(NotificationLog.event_id.in_(event_ids)).delete(synchronize_session=False)
            db.query(Event).filter(Event.source_id == s.id).delete(synchronize_session=False)
        db.query(Favorite).filter(Favorite.source_id == s.id).delete(synchronize_session=False)
        db.delete(s)

    if matching_sources:
        db.commit()

    referer = request.headers.get("referer") or "/schools"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/delete-user")
async def admin_delete_user(
    request: Request,
    user_id: int = Form(...),
    action_type: str = Form("withdraw"),
    db: Session = Depends(get_db)
):
    """管理者によるユーザーアカウントの処理（強制退会 または 完全削除）"""
    current_admin = get_current_user_optional(request, db)
    if not current_admin or not current_admin.is_admin:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    if current_admin.id == user_id:
        # 自分自身の削除は禁止
        referer = request.headers.get("referer") or "/admin"
        return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
        if action_type == "purge":
            # データベースからの完全物理削除
            db.delete(target_user)
            db.commit()
        else:
            # 論理退会（ステータスを退会済みに更新し、個人関連データをクリア）
            target_user.is_active = False
            target_user.withdrawn_at = datetime.utcnow()
            db.query(Favorite).filter(Favorite.user_id == target_user.id).delete()
            db.query(KeywordAlert).filter(KeywordAlert.user_id == target_user.id).delete()
            db.query(Event).filter(Event.user_id == target_user.id).delete()
            db.commit()

    referer = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/account/delete")
async def delete_my_account(
    request: Request,
    db: Session = Depends(get_db)
):
    """ログイン中ユーザー本人の退会（論理退会）処理"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # 論理退会処理（ステータスを退会済みに設定し、退会日時を記録）
    user.is_active = False
    user.withdrawn_at = datetime.utcnow()
    user.is_paid = False
    user.subscription_status = "canceled"

    # Stripeの定期課金（サブスクリプション）が残っていれば自動解約
    if STRIPE_SECRET_KEY and user.stripe_subscription_id:
        try:
            stripe.Subscription.cancel(user.stripe_subscription_id)
            print(f"[Account Deletion]: Canceled Stripe subscription {user.stripe_subscription_id} for user {user.username}")
        except Exception as e:
            print(f"[Account Deletion Warning]: Could not cancel Stripe subscription: {e}")

    # プライバシー保護・メール配信停止のため、個人登録データ（お気に入り、キーワード、個人予定）をクリア
    db.query(Favorite).filter(Favorite.user_id == user.id).delete()
    db.query(KeywordAlert).filter(KeywordAlert.user_id == user.id).delete()
    db.query(Event).filter(Event.user_id == user.id).delete()
    db.commit()

    # ログアウト完了（クッキー削除）してログイン画面へリダイレクト
    response = RedirectResponse(url="/login?msg=withdrawn", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="current_user", path="/")
    response.delete_cookie(key="access_token", path="/")
    return response

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
async def login_get(request: Request, msg: Optional[str] = None, next: Optional[str] = None):
    return templates.TemplateResponse(request=request, name="login.html", context={"msg": msg, "next_url": next})

@app.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    from sqlalchemy import func
    username_clean = username.strip()
    
    # ユーザー名またはメールアドレス（大文字小文字不問・前後空白除去）で検索
    user = db.query(User).filter(
        (User.username == username_clean) | (func.lower(User.email) == username_clean.lower())
    ).first()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "ユーザー名・メールアドレスまたはパスワードが正しくありません", "next_url": next}
        )

    if getattr(user, "is_active", True) is False:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "このアカウントは退会済みです。再度ご利用の際は新規会員登録をお願いいたします。", "next_url": next}
        )

    # 万が一リダイレクト未完了等で is_paid が False の場合の自己修復（Stripe自動同期）
    if not user.is_paid and STRIPE_SECRET_KEY:
        try:
            customers = stripe.Customer.list(email=user.email, limit=1)
            if customers.data:
                cus = customers.data[0]
                subs = stripe.Subscription.list(customer=cus.id, status="all", limit=1)
                if subs.data:
                    sub = subs.data[0]
                    if sub.status in ["active", "trialing"]:
                        user.is_paid = True
                        user.stripe_customer_id = cus.id
                        user.stripe_subscription_id = sub.id
                        user.subscription_status = sub.status
                        db.commit()
                        print(f"[Auto-Recovered Subscription]: User {user.username} activated via Stripe login sync.")
        except Exception as e:
            print(f"[Login Stripe Sync Warning]: {e}")

    redirect_target = next if (next and next.startswith("/")) else "/dashboard"
    res = RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
    res.set_cookie(
        key="current_user",
        value=urllib.parse.quote(user.username),
        httponly=True,
        path="/",
        samesite="lax",
        max_age=60 * 60 * 24 * 7
    )
    return res

@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request, db: Session = Depends(get_db)):
    """利用規約ページ"""
    user = get_current_user_optional(request, db)
    return templates.TemplateResponse(
        request=request,
        name="terms.html",
        context={"user": user}
    )

@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user and user.is_paid:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request=request, name="register.html", context={"user": user})

@app.post("/register", response_class=HTMLResponse)
async def register_post(
    request: Request,
    background_tasks: BackgroundTasks,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    email_clean = email.strip().lower()
    username_clean = username.strip()

    # 1. 既存のアクティブユーザー重複チェック
    existing_active = db.query(User).filter(
        User.is_active == True,
        (User.username == username_clean) | (User.email == email_clean)
    ).first()
    if existing_active:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "このユーザー名またはメールアドレスは既に登録されています"}
        )

    # 2. 無料トライアル利用歴の判定（メールアドレス基準）
    trial_history = db.query(TrialHistory).filter(TrialHistory.email == email_clean).first()
    is_first_time = (trial_history is None)

    # 3. ユーザーの取得または仮作成
    user = db.query(User).filter(
        (User.username == username_clean) | (User.email == email_clean)
    ).first()

    if user:
        # 退会済みユーザーの再登録
        user.username = username_clean
        user.email = email_clean
        user.hashed_password = hash_password(password)
        user.is_active = True
        user.withdrawn_at = None
        user.is_paid = False
        user.subscription_status = "pending"
    else:
        # 完全新規登録
        user = User(
            username=username_clean,
            email=email_clean,
            hashed_password=hash_password(password),
            is_paid=False,
            subscription_status="pending"
        )
        db.add(user)

    db.commit()
    db.refresh(user)

    # 4. 期間限定無料キャンペーンモード（カード決済スキップ・即時PRO会員化）
    if FREE_REGISTRATION_CAMPAIGN:
        user.is_paid = True
        user.subscription_status = "campaign_free"
        if is_first_time and not trial_history:
            db.add(TrialHistory(email=user.email))
        db.commit()

        background_tasks.add_task(
            EmailNotifier.notify_admin_new_user_registered,
            username=user.username,
            email=user.email
        )

        res = RedirectResponse(url="/dashboard?campaign_welcome=1", status_code=status.HTTP_303_SEE_OTHER)
        res.set_cookie(
            key="current_user",
            value=urllib.parse.quote(user.username),
            httponly=True,
            path="/",
            samesite="lax",
            max_age=60 * 60 * 24 * 7
        )
        return res

    # 5. 通常運用時の Stripe Checkout セッション作成
    if STRIPE_SECRET_KEY and STRIPE_PRICE_ID:
        try:
            base_url = str(request.base_url).rstrip("/")
            # 本番httpsプロキシ環境でhttpになる場合の補正
            if "ojuken-navi.com" in base_url and not base_url.startswith("https://"):
                base_url = base_url.replace("http://", "https://")

            session_params = {
                "mode": "subscription",
                "customer_email": user.email,
                "payment_method_types": ["card"],
                "managed_payments": {"enabled": False},
                "line_items": [
                    {
                        "price": STRIPE_PRICE_ID,
                        "quantity": 1,
                    }
                ],
                "metadata": {
                    "user_id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "is_first_time": "true" if is_first_time else "false"
                },
                "success_url": f"{base_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": f"{base_url}/payment/cancel"
            }

            # 初回登録のみ「30日間無料トライアル」を付与
            if is_first_time:
                session_params["subscription_data"] = {
                    "trial_period_days": 30,
                    "metadata": {
                        "user_id": str(user.id),
                        "is_first_time": "true"
                    }
                }
            else:
                session_params["subscription_data"] = {
                    "metadata": {
                        "user_id": str(user.id),
                        "is_first_time": "false"
                    }
                }

            checkout_session = stripe.checkout.Session.create(**session_params)
            return RedirectResponse(url=checkout_session.url, status_code=status.HTTP_303_SEE_OTHER)

        except Exception as e:
            print(f"[Stripe Checkout Error]: {e}")
            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={"error": f"決済画面の生成に失敗しました: {str(e)}"}
            )
    else:
        # Stripeキーが未設定の場合のフォールバック（ローカル開発用）
        user.is_paid = True
        user.subscription_status = "trialing" if is_first_time else "active"
        if is_first_time and not trial_history:
            db.add(TrialHistory(email=user.email))
        db.commit()

        background_tasks.add_task(
            EmailNotifier.notify_admin_new_user_registered,
            username=user.username,
            email=user.email
        )

        res = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        res.set_cookie(
            key="current_user",
            value=urllib.parse.quote(user.username),
            httponly=True,
            path="/",
            samesite="lax",
            max_age=60 * 60 * 24 * 7
        )
        return res

@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(
    request: Request,
    session_id: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db)
):
    """Stripe決済成功時のリダイレクト受け取り"""
    if not session_id or not STRIPE_SECRET_KEY:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        user_id_str = checkout_session.metadata.get("user_id") if checkout_session.metadata else None
        is_trial_str = checkout_session.metadata.get("is_first_time", "true") if checkout_session.metadata else "true"
        is_trial = (is_trial_str == "true")

        user = None
        if user_id_str:
            user = db.query(User).filter(User.id == int(user_id_str)).first()
        if not user and checkout_session.customer_email:
            user = db.query(User).filter(User.email == checkout_session.customer_email).first()

        if user:
            user.is_paid = True
            user.stripe_customer_id = checkout_session.customer
            user.stripe_subscription_id = checkout_session.subscription
            user.subscription_status = "trialing" if is_trial else "active"

            # 初回トライアル履歴を永続記録（再登録時の無料利用を恒久防止）
            existing_history = db.query(TrialHistory).filter(TrialHistory.email == user.email).first()
            if not existing_history:
                db.add(TrialHistory(email=user.email))

            db.commit()

            # 管理者へ通知
            background_tasks.add_task(
                EmailNotifier.notify_admin_new_user_registered,
                username=user.username,
                email=user.email
            )

            res = templates.TemplateResponse(
                request=request,
                name="payment_success.html",
                context={
                    "user": user,
                    "username": user.username,
                    "is_trial": is_trial
                }
            )
            # ログインCookieを発行
            res.set_cookie(
                key="current_user",
                value=urllib.parse.quote(user.username),
                httponly=True,
                path="/",
                samesite="lax",
                max_age=60 * 60 * 24 * 7
            )
            return res

    except Exception as e:
        print(f"[Payment Success Retrieval Error]: {e}")

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel(request: Request, db: Session = Depends(get_db)):
    """Stripe決済キャンセル時の案内画面"""
    user = get_current_user_optional(request, db)
    return templates.TemplateResponse(
        request=request,
        name="payment_cancel.html",
        context={"user": user}
    )

@app.get("/create-portal-session")
async def create_portal_session(request: Request, db: Session = Depends(get_db)):
    """Stripe カスタマーポータル（解約・カード変更）へリダイレクト"""
    user = get_current_user_required(request, db)
    if not STRIPE_SECRET_KEY or not user.stripe_customer_id:
        return RedirectResponse(url="/dashboard?msg=no_billing_info", status_code=status.HTTP_303_SEE_OTHER)

    try:
        base_url = str(request.base_url).rstrip("/")
        if "ojuken-navi.com" in base_url and not base_url.startswith("https://"):
            base_url = base_url.replace("http://", "https://")

        portal_session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=f"{base_url}/dashboard"
        )
        return RedirectResponse(url=portal_session.url, status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        print(f"[Customer Portal Error]: {e}")
        return RedirectResponse(url="/dashboard?msg=portal_error", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe Webhook（解約・請求更新の自動同期）"""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    event = None
    try:
        if webhook_secret and sig_header:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            # 署名シークレット未設定の場合はJSON直接デコード（開発/簡易連携時）
            event = json.loads(payload)
    except Exception as e:
        print(f"[Stripe Webhook Verification Error]: {e}")
        return JSONResponse(status_code=400, content={"error": str(e)})

    event_type = event.get("type")
    data_obj = event.get("data", {}).get("object", {})

    print(f"[Stripe Webhook Event Received]: {event_type}")

    # サブスクリプション解約時
    if event_type == "customer.subscription.deleted":
        sub_id = data_obj.get("id")
        user = db.query(User).filter(User.stripe_subscription_id == sub_id).first()
        if user:
            user.is_paid = False
            user.subscription_status = "canceled"
            db.commit()
            print(f"[Subscription Canceled]: User {user.username} subscription canceled.")

    # サブスクリプションステータス変更時（更新成功、トライアル終了、支払い遅延等）
    elif event_type in ["customer.subscription.updated"]:
        sub_id = data_obj.get("id")
        status_val = data_obj.get("status")
        user = db.query(User).filter(User.stripe_subscription_id == sub_id).first()
        if user:
            user.subscription_status = status_val
            user.is_paid = (status_val in ["active", "trialing"])
            db.commit()
            print(f"[Subscription Updated]: User {user.username} status is now {status_val}.")

    return JSONResponse(content={"status": "success"})

@app.get("/logout")
async def logout():
    res = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    res.delete_cookie(key="current_user", path="/")
    return res

# --- 個人情報保護・セキュリティ規定ルート ---

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, db: Session = Depends(get_db)):
    """個人情報保護方針・データ管理およびセキュリティ規定ページ"""
    user = get_current_user_optional(request, db)
    return templates.TemplateResponse(
        request=request,
        name="privacy.html",
        context={"user": user}
    )

@app.get("/security", response_class=HTMLResponse)
async def security_page():
    """セキュリティ規定へのエイリアスリダイレクト"""
    return RedirectResponse(url="/privacy#section-4", status_code=status.HTTP_301_MOVED_PERMANENTLY)

# --- 運営会社情報（日本資産運用機構）ルート ---

@app.get("/company", response_class=HTMLResponse)
async def company_page(request: Request, db: Session = Depends(get_db)):
    """運営会社（日本資産運用機構）情報ページ"""
    user = get_current_user_optional(request, db)
    return templates.TemplateResponse(
        request=request,
        name="company.html",
        context={"user": user}
    )

@app.get("/about", response_class=HTMLResponse)
async def about_page():
    """会社概要へのエイリアスリダイレクト"""
    return RedirectResponse(url="/company", status_code=status.HTTP_301_MOVED_PERMANENTLY)

# --- 管理者専用：社内戦略レポート・AI討議ドキュメント管理 ---

from app.reports_registry import get_all_reports, get_report_by_id, delete_report
from app.ai_chat.agent_discussion_engine import AgentDiscussionEngine, TEAM_PRESETS

@app.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports_list_page(request: Request, db: Session = Depends(get_db)):
    """管理者専用：戦略レポート一覧画面（日付・枝番順）"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next={request.url.path}&msg=admin_required", status_code=status.HTTP_303_SEE_OTHER)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ページが見つかりません")

    reports = get_all_reports()
    return templates.TemplateResponse(
        request=request,
        name="admin_reports_list.html",
        context={"user": user, "reports": reports}
    )

@app.get("/admin/reports/new", response_class=HTMLResponse)
async def admin_report_create_page(request: Request, db: Session = Depends(get_db)):
    """管理者専用：新規AIエージェント討議＆レポート生成画面"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next={request.url.path}&msg=admin_required", status_code=status.HTTP_303_SEE_OTHER)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ページが見つかりません")

    return templates.TemplateResponse(
        request=request,
        name="admin_report_create.html",
        context={"user": user, "team_presets": TEAM_PRESETS}
    )

@app.post("/admin/reports/generate")
async def admin_report_generate(
    request: Request,
    topic: str = Form(...),
    constraints: str = Form(""),
    team_type: str = Form("bizdev"),
    custom_team_name: str = Form(""),
    db: Session = Depends(get_db)
):
    """管理者専用：AIエージェントチーム討議を実行し、構造化レポートを自動生成・保存"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next=/admin/reports/new&msg=admin_required", status_code=status.HTTP_303_SEE_OTHER)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="管理者権限が必要です")

    clean_topic = (topic or "").strip()
    if not clean_topic:
        return RedirectResponse(url="/admin/reports/new?error=empty_topic", status_code=status.HTTP_303_SEE_OTHER)

    try:
        new_report = await AgentDiscussionEngine.run_discussion_and_generate_report(
            topic=clean_topic,
            constraints=constraints,
            team_type=team_type,
            custom_team_name=custom_team_name
        )
        return RedirectResponse(url=f"/admin/reports/{new_report['id']}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        print(f"[admin_report_generate] Error: {e}")
        return RedirectResponse(url="/admin/reports?error=generation_failed", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/reports/{report_id}", response_class=HTMLResponse)
async def admin_report_detail_page(report_id: str, request: Request, db: Session = Depends(get_db)):
    """管理者専用：個別戦略レポート閲覧画面（日付・枝番ID指定）"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url=f"/login?next={request.url.path}&msg=admin_required", status_code=status.HTTP_303_SEE_OTHER)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ページが見つかりません")

    report_meta = get_report_by_id(report_id)
    if not report_meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたレポートが見つかりません")

    template_name = report_meta.get("template") or "report_dynamic.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={"user": user, "report": report_meta}
    )

@app.get("/admin/reports/{report_id}/download")
async def admin_report_download(report_id: str, request: Request, db: Session = Depends(get_db)):
    """管理者専用：レポートをMarkdownファイル (.md) としてダウンロード"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="管理者権限が必要です")

    report_meta = get_report_by_id(report_id)
    if not report_meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="指定されたレポートが見つかりません")

    content_md = report_meta.get("content_markdown", "")
    filename = f"{report_id}.md"
    return Response(
        content=content_md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.post("/admin/reports/{report_id}/delete")
async def admin_report_delete(report_id: str, request: Request, db: Session = Depends(get_db)):
    """管理者専用：レポートの削除"""
    user = get_current_user_optional(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="管理者権限が必要です")

    delete_report(report_id)
    return RedirectResponse(url="/admin/reports?msg=deleted", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/report")
async def legacy_report_redirect(request: Request, db: Session = Depends(get_db)):
    """旧/reportへのアクセス制御：管理者のみ最新レポートへ誘導、それ以外はログインまたは404"""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/login?next=/admin/reports&msg=admin_required", status_code=status.HTTP_303_SEE_OTHER)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ページが見つかりません")
    
    # 最新レポートを取得してリダイレクト
    reports = get_all_reports()
    target_id = reports[0]["id"] if reports else "20260926-01-education-business"
    return RedirectResponse(url=f"/admin/reports/{target_id}", status_code=status.HTTP_302_FOUND)




