import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import User, Source, KeywordAlert

def test_alerts_and_presets():
    print("=== [キーワードアラート ＆ 巡回先プリセット拡張機能 テスト] ===")

    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    # 1. プリセットソースのロード確認
    db = SessionLocal()
    try:
        sources = db.query(Source).all()
        print(f"\n1. プリセットソース読み込み検証...")
        print(f"   --> 登録済みソース総数: {len(sources)} 件")
        source_names = [s.name for s in sources]
        for name in source_names:
            print(f"       - {name}")
        assert len(sources) >= 6

        # 2. ユーザーログイン ＆ キーワードアラート追加テスト
        print("\n2. キーワードアラート追加 API テスト...")
        user = db.query(User).filter(User.username == "demo_user").first()
        assert user is not None

        # demo_user でログイン Cookie 保持模擬
        client.post("/login", data={"username": "demo_user", "password": "password123"})

        res_add_kw = client.post("/keyword-alerts", data={"keyword": "補欠判定"}, follow_redirects=True)
        assert res_add_kw.status_code == 200

        alerts = db.query(KeywordAlert).filter(KeywordAlert.user_id == user.id).all()
        alert_kws = [a.keyword for a in alerts]
        print(f"   --> ユーザー登録アラートワード一覧: {alert_kws}")
        assert "補欠判定" in alert_kws

        # 3. TOP一覧画面でのアラートマッチングテスト
        print("\n3. データ一覧画面でのアラートハイライト検証...")
        res_home = client.get("/")
        assert res_home.status_code == 200
        assert "アラート" in res_home.text
        print("   --> アラートハイライトバッジ 200 OK")

        # 4. アラート削除 API テスト
        target_alert = db.query(KeywordAlert).filter(KeywordAlert.user_id == user.id, KeywordAlert.keyword == "補欠判定").first()
        if target_alert:
            res_del = client.post(f"/keyword-alerts/{target_alert.id}/delete", follow_redirects=True)
            assert res_del.status_code == 200
            print("   --> キーワードアラート削除 API 正常動作 200 OK")

        print("\n=== [キーワードアラート ＆ プリセット拡張機能の全テスト成功！] ===")

    finally:
        db.close()

if __name__ == "__main__":
    test_alerts_and_presets()
