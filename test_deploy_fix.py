import sys
from app.main import auto_migrate_db, app
from fastapi.testclient import TestClient

def test_deploy_fix_and_app_startup():
    # 1. auto_migrate_db の実行確認
    auto_migrate_db()
    
    # 2. アプリの起動と主要エンドポイントのテスト
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200, "App should start up without errors"

    res_events = client.get("/api/calendar-events")
    assert res_events.status_code == 200, "Calendar events query should run without missing column error"

    print("[SUCCESS] Deploy fix test passed successfully! No missing column error.")

if __name__ == "__main__":
    test_deploy_fix_and_app_startup()
