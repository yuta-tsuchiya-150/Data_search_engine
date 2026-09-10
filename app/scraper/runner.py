import os
import yaml
import json
import httpx
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models.schema import Category, Source, Event
from app.scraper.parser import GenericHTMLParser

class ScraperRunner:
    """
    設定ファイルの読み込み、サイトの巡回・スクレイピングおよびDBへの新規イベント格納を担当するエンジン
    """
    @staticmethod
    def load_configs_from_directory(config_dir: str, db: Session):
        """
        yaml設定ファイルをスキャンし、カテゴリとソースのマスタ情報をDBに登録/更新
        """
        if not os.path.exists(config_dir):
            return

        for filename in os.listdir(config_dir):
            if filename.endswith(".yaml") or filename.endswith(".yml"):
                filepath = os.path.join(config_dir, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                
                cat_id = data.get("category_id")
                cat_name = data.get("category_name")
                cat_desc = data.get("description", "")
                
                if not cat_id or not cat_name:
                    continue

                category = db.query(Category).filter(Category.category_id == cat_id).first()
                if not category:
                    category = Category(category_id=cat_id, name=cat_name, description=cat_desc)
                    db.add(category)
                    db.commit()
                    db.refresh(category)

                sources_data = data.get("sources", [])
                for s_data in sources_data:
                    source_id = s_data.get("id")
                    source = db.query(Source).filter(Source.source_id == source_id).first()
                    selectors_json = json.dumps(s_data.get("selectors", {}), ensure_ascii=False)
                    
                    if not source:
                        source = Source(
                            source_id=source_id,
                            category_id=category.id,
                            name=s_data.get("name"),
                            type=s_data.get("type", "school"),
                            url=s_data.get("url"),
                            schedule_interval_minutes=s_data.get("schedule_interval_minutes", 60),
                            selectors_json=selectors_json
                        )
                        db.add(source)
                    else:
                        source.name = s_data.get("name")
                        source.url = s_data.get("url")
                        source.selectors_json = selectors_json
                    
                db.commit()

    @staticmethod
    async def run_scrape_for_source(source: Source, db: Session) -> List[Event]:
        """
        指定されたソースのWebページを取得・解析し、未登録の新規イベントを保存
        """
        selectors = json.loads(source.selectors_json)
        new_events = []

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                response = await client.get(source.url)
                if response.status_code != 200:
                    print(f"Failed to fetch {source.url}: Status {response.status_code}")
                    return []
                
                html_content = response.text
                parsed_items = GenericHTMLParser.parse_html(html_content, source.url, selectors)

                for item in parsed_items:
                    title = item.get("title")
                    if not title:
                        continue

                    # 重複チェック（同一ソースかつ同一タイトルの有無）
                    existing = db.query(Event).filter(
                        Event.source_id == source.id,
                        Event.title == title
                    ).first()

                    if not existing:
                        from app.models.schema import resolve_official_url
                        raw_url = item.get("link", source.url)
                        resolved_url = resolve_official_url(raw_url, source)
                        new_event = Event(
                            source_id=source.id,
                            title=title,
                            content=item.get("content", ""),
                            url=resolved_url,
                            published_date=item.get("date", ""),
                            event_date=item.get("event_date", ""),
                            location=item.get("location", ""),
                            is_notified=False
                        )
                        db.add(new_event)
                        new_events.append(new_event)

                from datetime import datetime
                source.last_scraped_at = datetime.utcnow()
                db.commit()
                for e in new_events:
                    db.refresh(e)

        except Exception as e:
            print(f"Error scraping {source.name} ({source.url}): {e}")

        return new_events

    @staticmethod
    async def run_all_scrapers(db: Session, respect_interval: bool = False) -> List[Event]:
        """
        登録されている全ソースの巡回を一括実行 (respect_interval=Trueの場合は設定された巡回時間間隔を満たしたソースのみ実行)
        """
        from datetime import datetime
        sources = db.query(Source).all()
        all_new_events = []
        now = datetime.utcnow()
        for source in sources:
            if respect_interval and source.last_scraped_at and source.schedule_interval_minutes:
                minutes_since_last = (now - source.last_scraped_at).total_seconds() / 60.0
                if minutes_since_last < source.schedule_interval_minutes:
                    continue  # まだ指定の巡回時間に達していないためスキップ

            new_events = await ScraperRunner.run_scrape_for_source(source, db)
            all_new_events.extend(new_events)
        return all_new_events
