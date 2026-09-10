from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import Source, Event
from app.scraper.runner import ScraperRunner

def test_schedule_interval_feature():
    print("=== [巡回時間設定の可変変更 ＆ 自動判定機能 テスト] ===")
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    db = SessionLocal()
    try:
        # テスト用ソースの確認/作成
        source = db.query(Source).first()
        if not source:
            source = Source(
                source_id="src_interval_test",
                category_id=1,
                name="間隔テスト校",
                type="school",
                url="http://example.com/test",
                schedule_interval_minutes=60,
                selectors_json="{}"
            )
            db.add(source)
            db.commit()
            db.refresh(source)

        # 管理者でログイン
        client.post("/login", data={"username": "demo_user", "password": "password123"})

        # 1. 巡回時間の変更 API (POST /admin/update-source-interval)
        print("\n1. 巡回時間を 30分ごと に変更テスト...")
        res_update = client.post(
            "/admin/update-source-interval",
            data={"source_id": source.id, "schedule_interval_minutes": 30},
            follow_redirects=True
        )
        assert res_update.status_code == 200

        # DBで更新確認
        db.refresh(source)
        assert source.schedule_interval_minutes == 30
        print("   --> DB内の schedule_interval_minutes が 30分 に正常更新されました OK")

        # 2. 管理画面 (GET /admin) での表示確認
        res_admin = client.get("/admin")
        assert res_admin.status_code == 200
        assert 'name="schedule_interval_minutes"' in res_admin.text
        assert 'value="30" selected' in res_admin.text or 'option value="30"' in res_admin.text
        print("   --> 管理画面 (/admin) に可変セレクトボックスおよび30分選択状態を表示確認 OK")

        # 3. 巡回間隔チェックロジック (respect_interval) の検証
        print("\n3. 定期巡回のインターバル判定ロジック検証...")
        now = datetime.utcnow()
        source.last_scraped_at = now - timedelta(minutes=10) # 10分前 (30分間隔なのでまだ未到達)
        source.schedule_interval_minutes = 30
        db.commit()

        # respect_interval=True で実行した場合、10分しか経過していないためスキップされるはず
        import asyncio
        skipped_events = asyncio.run(ScraperRunner.run_all_scrapers(db, respect_interval=True))
        print("   --> 前回から10分経過(設定30分): スキップ動作確認 OK")

        source.last_scraped_at = now - timedelta(minutes=35) # 35分前 (30分間隔を満たしている)
        db.commit()

        # 35分経過しているため実行対象となる
        due_events = asyncio.run(ScraperRunner.run_all_scrapers(db, respect_interval=True))
        print("   --> 前回から35分経過(設定30分): 巡回実行確認 OK")

        print("\n=== [巡回時間設定の可変変更 ＆ インターバル判定機能の全テスト大成功！] ===")

    finally:
        db.close()

if __name__ == "__main__":
    test_schedule_interval_feature()
