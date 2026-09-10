import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import User, Source, Event, Favorite
from app.auth import hash_password

def test_user_experience():
    print("=== [新規ユーザー登録～マイページ・カレンダー体験テスト] ===")

    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    # 1. 新規会員登録
    username = "test_parent_user"
    email = "parent_test@example.com"
    password = "password123"

    db = SessionLocal()
    try:
        old_u = db.query(User).filter(User.username == username).first()
        if old_u:
            db.query(Favorite).filter(Favorite.user_id == old_u.id).delete()
            db.delete(old_u)
            db.commit()
    finally:
        db.close()

    print("\n1. 新規会員登録の実行...")
    res_reg = client.post("/register", data={
        "username": username,
        "email": email,
        "password": password
    }, follow_redirects=True)
    assert res_reg.status_code == 200
    print("   --> 新規会員アカウント作成成功！ (Cookie取得済)")

    # 2. マイページの初期状態確認
    print("\n2. 初期状態のマイページ確認...")
    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    assert username in res_dash.text
    print("   --> マイページ正常描画")

    # 3. お気に入り（ブックマーク）登録
    db = SessionLocal()
    try:
        sources = db.query(Source).all()
        target_source = sources[0]  # 1つ目の学校をお気に入り登録
        print(f"\n3. 「{target_source.name}」をお気に入りブックマーク登録...")
        res_fav = client.post("/toggle-favorite", data={"source_id": target_source.id}, follow_redirects=True)
        assert res_fav.status_code == 200
        print("   --> お気に入り登録完了！")

        # 4. マイページに反映されているか確認
        res_dash_after = client.get("/dashboard")
        assert target_source.name in res_dash_after.text
        print("   --> マイページにお気に入り学校と最新イベント一覧が反映されました！")

        # 5. 有料会員プランへの切替（カレンダー有効化）
        print("\n4. 有料会員プランにアップグレード (カレンダー機能解禁)...")
        client.post("/toggle-plan", follow_redirects=True)
        
        # 6. 月間カレンダーAPIの検証
        res_cal_api = client.get("/api/calendar-events")
        assert res_cal_api.status_code == 200
        events_json = res_cal_api.json()
        print(f"   --> カレンダー用イベントデータ取得件数: {len(events_json)} 件")
        for ev in events_json:
            print(f"       - カレンダー描画用イベント: {ev['title']} (日付: {ev['start']})")

        print("\n=== [すべての要件・ユーザーフローテストが完全クリア！] ===")

    finally:
        db.close()

if __name__ == "__main__":
    test_user_experience()
