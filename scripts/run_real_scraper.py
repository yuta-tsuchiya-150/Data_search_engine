import os
import sys
from datetime import datetime

# Windows文字コード対策
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# プロジェクトルートをパスに追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.database import SessionLocal
from app.scraper.real_school_scraper import sync_real_school_events

def main():
    print(f"[{datetime.now()}] === Starting Real School & Cram School Scraper Batch ===")
    db = SessionLocal()
    try:
        ins, upd, events = sync_real_school_events(db)
        print(f"[{datetime.now()}] Scrape finished successfully: {ins} inserted, {upd} updated.")
        for ev in events[:5]:
            print(f"  * [{ev.source.name if ev.source else 'Unknown'}] {ev.title} (Date: {ev.event_date})")
    except Exception as e:
        print(f"[{datetime.now()}] Error during scraping batch: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
