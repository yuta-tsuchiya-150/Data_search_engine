import re
import sys
import logging
from datetime import datetime
from urllib.parse import urljoin
from typing import List, Dict, Any, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models.schema import Category, Source, Event
from app.notifier.email_service import EmailNotifier

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def parse_japanese_date(text: str) -> str:
    """「2026年10月15日(土)」や「6月4日（木）」などの和文表記を YYYY-MM-DD 形式に正規化"""
    if not text:
        return ""
    # 202X年M月D日
    m1 = re.search(r'(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})', text)
    if m1:
        y, m, d = m1.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    # M月D日 (年は現在または翌年と推論)
    m2 = re.search(r'(\d{1,2})[月/\-](\d{1,2})', text)
    if m2:
        m, d = m2.groups()
        current_year = datetime.now().year
        return f"{current_year:04d}-{int(m):02d}-{int(d):02d}"
    return ""

def clean_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

class RealSchoolScraper:
    """
    東京・神奈川の主要私立小学校および大手幼児教室の本番Webページから
    最新イベント・説明会・模試情報を自動収集するスクレイピングエンジン
    """

    @classmethod
    def scrape_all_real_sources(cls) -> List[Dict[str, Any]]:
        """全ターゲットサイトからイベントを並行/順次収集"""
        all_events: List[Dict[str, Any]] = []

        # 1. 大手幼児教室
        all_events.extend(cls.scrape_rieikai())
        all_events.extend(cls.scrape_kogumakai())

        # 2. 主要私立小学校
        all_events.extend(cls.scrape_rikkyo_primary())
        all_events.extend(cls.scrape_aoyama_primary())
        all_events.extend(cls.scrape_waseda_primary())
        all_events.extend(cls.scrape_senzoku_primary())

        return all_events

    # -------------------------------------------------------------
    # 1. 理英会 (神奈川・東京エリア)
    # -------------------------------------------------------------
    @classmethod
    def scrape_rieikai(cls) -> List[Dict[str, Any]]:
        events = []
        base_url = "https://www.rieikai.com"
        target_urls = [
            ("https://www.rieikai.com/kanagawa/", "神奈川エリア"),
            ("https://www.rieikai.com/exam/", "首都圏オープン模試")
        ]

        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
            for url, area in target_urls:
                try:
                    res = client.get(url)
                    if res.status_code != 200:
                        continue
                    soup = BeautifulSoup(res.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        txt = clean_text(a.get_text())
                        href = a["href"]
                        if not any(k in href for k in ["_news/", "/exam/", "/event/"]):
                            continue
                        if not any(w in txt for w in ["模試", "テスト", "講習", "ゼミ", "説明会", "CAMP", "体験", "イベント"]):
                            continue
                        if len(txt) < 8 or len(txt) > 120:
                            continue

                        full_url = urljoin(base_url, href)
                        ev_date = parse_japanese_date(txt)
                        
                        tag = "【模試】" if any(w in txt for w in ["模試", "テスト"]) else "【講習・ゼミ】"
                        events.append({
                            "source_id": "rieikai",
                            "source_name": f"理英会 ({area})",
                            "source_type": "cram_school",
                            "source_url": "https://www.rieikai.com/",
                            "title": f"{tag} {txt}",
                            "content": f"理英会 {area}の最新受験プログラムです。志望校合格に向けた重要対策イベントです。",
                            "url": full_url,
                            "event_date": ev_date,
                            "location": f"理英会 {area}各校舎",
                            "published_date": datetime.now().strftime("%Y-%m-%d")
                        })
                except Exception as e:
                    logger.warning(f"Error scraping Rieikai ({url}): {e}")

        return events

    # -------------------------------------------------------------
    # 2. こぐま会 (東京・お受験幼児教室)
    # -------------------------------------------------------------
    @classmethod
    def scrape_kogumakai(cls) -> List[Dict[str, Any]]:
        events = []
        base_url = "https://www.kogumakai.co.jp/"
        try:
            with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
                res = client.get(base_url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        txt = clean_text(a.get_text())
                        href = a["href"]
                        if any(w in txt for w in ["模擬テスト", "特別講座", "セミナー", "診断テスト", "入試対策"]):
                            full_url = urljoin(base_url, href)
                            ev_date = parse_japanese_date(txt)
                            tag = "【公開模試】" if "テスト" in txt else "【特別講座】"
                            events.append({
                                "source_id": "kogumasakai",
                                "source_name": "こぐま会 (幼児教育実践研究所)",
                                "source_type": "cram_school",
                                "source_url": "https://www.kogumakai.co.jp/",
                                "title": f"{tag} {txt}",
                                "content": "こぐま会による有名私立小学校・国立小学校受験対策テストおよびセミナー情報です。",
                                "url": full_url,
                                "event_date": ev_date,
                                "location": "こぐま会各教室 / オンライン",
                                "published_date": datetime.now().strftime("%Y-%m-%d")
                            })
        except Exception as e:
            logger.warning(f"Error scraping Kogumakai: {e}")
        return events

    # -------------------------------------------------------------
    # 3. 立教小学校 (東京都豊島区)
    # -------------------------------------------------------------
    @classmethod
    def scrape_rikkyo_primary(cls) -> List[Dict[str, Any]]:
        events = []
        guidance_url = "https://prim.rikkyo.ac.jp/entrance/openschool/guidance2026.html"
        try:
            with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
                res = client.get(guidance_url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    # テーブル行ごとの開催日・内容・会場の抽出
                    current_date = ""
                    current_location = "立教小学校 (東京都豊島区目白)"
                    current_title = "学校説明会・授業参観"

                    for tr in soup.find_all("tr"):
                        cells = [clean_text(c.get_text()) for c in tr.find_all(["th", "td"])]
                        if len(cells) >= 2:
                            header, val = cells[0], cells[1]
                            if "開催日" in header:
                                current_date = parse_japanese_date(val)
                            elif "会場" in header:
                                current_location = val
                            elif "内容" in header:
                                current_title = val.split("・")[0] if "・" in val else val[:40]
                                if current_date:
                                    events.append({
                                        "source_id": "rikkyo_primary",
                                        "source_name": "立教小学校",
                                        "source_type": "school",
                                        "source_url": "https://prim.rikkyo.ac.jp/",
                                        "title": f"【学校説明会】立教小学校 {current_title}",
                                        "content": f"立教小学校の公開説明会・学校探検です。内容: {val}",
                                        "url": guidance_url,
                                        "event_date": current_date,
                                        "location": current_location,
                                        "published_date": datetime.now().strftime("%Y-%m-%d")
                                    })
        except Exception as e:
            logger.warning(f"Error scraping Rikkyo Primary: {e}")
        return events

    # -------------------------------------------------------------
    # 4. 青山学院初等部 (東京都渋谷区)
    # -------------------------------------------------------------
    @classmethod
    def scrape_aoyama_primary(cls) -> List[Dict[str, Any]]:
        events = []
        target_url = "https://www.age.aoyama.ed.jp/admission/explanation.html"
        try:
            with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
                res = client.get(target_url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    main_txt = soup.get_text(" ")
                    ev_date = parse_japanese_date(main_txt)
                    title = "青山学院初等部 入試学校説明会"
                    events.append({
                        "source_id": "aoyama_gakuin",
                        "source_name": "青山学院初等部",
                        "source_type": "school",
                        "source_url": "https://www.age.aoyama.ed.jp/",
                        "title": f"【学校説明会】{title}",
                        "content": "青山学院初等部の教育理念、学校生活、2026年度入試概要に関する公式説明会です。",
                        "url": target_url,
                        "event_date": ev_date or f"{datetime.now().year}-05-20",
                        "location": "青山学院初等部 (東京都渋谷区渋谷)",
                        "published_date": datetime.now().strftime("%Y-%m-%d")
                    })
        except Exception as e:
            logger.warning(f"Error scraping Aoyama Primary: {e}")
        return events

    # -------------------------------------------------------------
    # 5. 早稲田実業学校初等部 (東京都国分寺市)
    # -------------------------------------------------------------
    @classmethod
    def scrape_waseda_primary(cls) -> List[Dict[str, Any]]:
        events = []
        target_url = "https://www.wasedajg.ed.jp/elementary/exam-e/explain-e/"
        try:
            with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
                res = client.get(target_url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    ev_date = parse_japanese_date(soup.get_text(" "))
                    events.append({
                        "source_id": "waseda_jitsugyo",
                        "source_name": "早稲田実業学校初等部",
                        "source_type": "school",
                        "source_url": "https://www.wasedajg.ed.jp/elementary/",
                        "title": "【学校説明会】早稲田実業学校初等部 学校説明会・入試説明",
                        "content": "早稲田実業学校初等部の学校説明会、入試日程および募集要項に関する公式案内です。",
                        "url": target_url,
                        "event_date": ev_date or f"{datetime.now().year}-06-15",
                        "location": "早稲田実業学校国分寺キャンパス",
                        "published_date": datetime.now().strftime("%Y-%m-%d")
                    })
        except Exception as e:
            logger.warning(f"Error scraping Waseda Primary: {e}")
        return events

    # -------------------------------------------------------------
    # 6. 洗足学園小学校 (神奈川県川崎市)
    # -------------------------------------------------------------
    @classmethod
    def scrape_senzoku_primary(cls) -> List[Dict[str, Any]]:
        events = []
        target_url = "https://www.senzoku.ed.jp/elementary/admissions/session/"
        try:
            with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True, verify=False) as client:
                res = client.get(target_url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    for item in soup.select("article, .session-item, .entry-content p, tr, li"):
                        txt = clean_text(item.get_text())
                        if any(w in txt for w in ["説明会", "公開授業", "オープンスクール", "見学会"]) and len(txt) < 150:
                            ev_date = parse_japanese_date(txt)
                            if ev_date:
                                events.append({
                                    "source_id": "senzoku_primary",
                                    "source_name": "洗足学園小学校 (神奈川)",
                                    "source_type": "school",
                                    "source_url": "https://www.senzoku.ed.jp/elementary/",
                                    "title": f"【説明会・見学会】洗足学園小学校 {txt[:40]}",
                                    "content": f"洗足学園小学校の入試関連イベントです。{txt}",
                                    "url": target_url,
                                    "event_date": ev_date,
                                    "location": "洗足学園小学校 (神奈川県川崎市高津区)",
                                    "published_date": datetime.now().strftime("%Y-%m-%d")
                                })
        except Exception as e:
            logger.warning(f"Error scraping Senzoku Primary: {e}")
        return events

def sync_real_school_events(db: Session) -> Tuple[int, int, List[Event]]:
    """
    スクレイピングした本番データをDB（Supabase / SQLite）へ安全にUPSERT同期
    手動登録データ（user_id が入っているもの等）は完全保護
    戻り値: (新規登録件数, 更新件数, 新規追加されたEventリスト)
    """
    raw_events = RealSchoolScraper.scrape_all_real_sources()
    if not raw_events:
        return 0, 0, []

    # カテゴリの存在確認・取得
    category = db.query(Category).filter(Category.category_id == "elementary_school").first()
    if not category:
        category = Category(
            category_id="elementary_school",
            name="小学校お受験情報",
            description="東京・神奈川の主要小学校および大手進学塾の公式Webサイトから最新イベントを自動収集"
        )
        db.add(category)
        db.commit()
        db.refresh(category)

    inserted_count = 0
    updated_count = 0
    newly_added_events: List[Event] = []

    # Sourceごとにイベントを整理
    for item in raw_events:
        sid = item["source_id"]
        source = db.query(Source).filter(Source.source_id == sid).first()
        if not source:
            source = Source(
                source_id=sid,
                category_id=category.id,
                name=item["source_name"],
                type=item.get("source_type", "school"),
                url=item["source_url"],
                schedule_interval_minutes=240,
                selectors_json="{}"
            )
            db.add(source)
            db.commit()
            db.refresh(source)
        else:
            # 最新の名称・URLを同期
            source.name = item["source_name"]
            source.url = item["source_url"]

        source.last_scraped_at = datetime.utcnow()

        # 重複検知（同一Source内でタイトルまたはURLが一致、かつ手動カスタム予定 user_id is None のもの）
        existing_event = db.query(Event).filter(
            Event.source_id == source.id,
            Event.user_id.is_(None),
            (Event.url == item["url"]) | (Event.title == item["title"])
        ).first()

        if existing_event:
            # 既存イベントがある場合は日程や内容の差分更新 (UPSERT)
            changed = False
            if item.get("event_date") and existing_event.event_date != item["event_date"]:
                existing_event.event_date = item["event_date"]
                changed = True
            if item.get("location") and existing_event.location != item["location"]:
                existing_event.location = item["location"]
                changed = True
            if item.get("content") and existing_event.content != item["content"]:
                existing_event.content = item["content"]
                changed = True
            if changed:
                updated_count += 1
        else:
            # 新規イベントの追加
            new_event = Event(
                source_id=source.id,
                user_id=None,  # 公開公式イベント
                title=item["title"],
                content=item.get("content", ""),
                url=item.get("url", ""),
                published_date=item.get("published_date", datetime.now().strftime("%Y-%m-%d")),
                event_date=item.get("event_date"),
                location=item.get("location", ""),
                is_notified=False
            )
            db.add(new_event)
            db.flush()
            newly_added_events.append(new_event)
            inserted_count += 1

    db.commit()

    # 新規イベントが回収された場合はマスターへメール通知
    if newly_added_events:
        try:
            EmailNotifier.notify_admin_harvest_report(newly_added_events)
        except Exception as e:
            logger.warning(f"Failed to send harvest notification email: {e}")

    return inserted_count, updated_count, newly_added_events

if __name__ == "__main__":
    from app.database import SessionLocal
    print("🚀 Starting real school & cram school scraper (Tokyo & Kanagawa)...")
    db = SessionLocal()
    try:
        ins, upd, evs = sync_real_school_events(db)
        print(f"🎉 Scraping finished! Inserted: {ins} new events, Updated: {upd} existing events.")
        for ev in evs[:10]:
            print(f"  + [{ev.source.name if ev.source else ''}] {ev.title} (Date: {ev.event_date}, Loc: {ev.location})")
    finally:
        db.close()
