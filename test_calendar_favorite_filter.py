from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import User, Source, Event, Favorite
from app.auth import hash_password

def test_calendar_favorite_filter():
    print("=== [カレンダーお気に入り表示切り替え機能 テスト] ===")
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    db = SessionLocal()
    try:
        # テスト用ユーザー作成
        user = db.query(User).filter(User.username == "cal_test_user").first()
        if not user:
            user = User(username="cal_test_user", email="cal@example.com", hashed_password=hash_password("pass123"))
            db.add(user)
            db.commit()
            db.refresh(user)

        # テスト用ソース2件とイベントを作成
        s1 = db.query(Source).filter(Source.source_id == "src_fav_school").first()
        if not s1:
            s1 = Source(source_id="src_fav_school", category_id=1, name="お気に入り校", type="school", url="http://example.com/1", schedule_interval_minutes=60, selectors_json="{}")
            db.add(s1)
            db.commit()
            db.refresh(s1)

        s2 = db.query(Source).filter(Source.source_id == "src_other_school").first()
        if not s2:
            s2 = Source(source_id="src_other_school", category_id=1, name="その他校", type="school", url="http://example.com/2", schedule_interval_minutes=60, selectors_json="{}")
            db.add(s2)
            db.commit()
            db.refresh(s2)

        # お気に入り登録 (s1のみ)
        fav = db.query(Favorite).filter(Favorite.user_id == user.id, Favorite.source_id == s1.id).first()
        if not fav:
            fav = Favorite(user_id=user.id, source_id=s1.id)
            db.add(fav)

        # イベント作成
        e1 = db.query(Event).filter(Event.source_id == s1.id).first()
        if not e1:
            db.add(Event(source_id=s1.id, title="お気に入り校イベント", url="http://example.com/e1", event_date="2026-10-01"))
        e2 = db.query(Event).filter(Event.source_id == s2.id).first()
        if not e2:
            db.add(Event(source_id=s2.id, title="その他校イベント", url="http://example.com/e2", event_date="2026-10-02"))
        db.commit()

        # 1. ログイン
        client.post("/login", data={"username": "cal_test_user", "password": "pass123"})

        # 2. 画面上部ヘッダーリンク (/calendar)
        res_all = client.get("/calendar")
        assert res_all.status_code == 200
        assert "var currentFavOnly = false;" in res_all.text
        print("   --> ヘッダーからのアクセス (/calendar) : 全イベント表示モード OK")

        # 3. マイページからの「カレンダーで見る」リンク (/calendar?favorite_only=true)
        res_fav = client.get("/calendar?favorite_only=true")
        assert res_fav.status_code == 200
        assert "var currentFavOnly = true;" in res_fav.text
        print("   --> マイページからのアクセス (/calendar?favorite_only=true) : お気に入り学校のみ表示モード OK")

        # 4. API テスト (/api/calendar-events?favorite_only=true)
        res_api_all = client.get("/api/calendar-events?favorite_only=false")
        assert res_api_all.status_code == 200
        all_events_data = res_api_all.json()
        assert len(all_events_data) >= 2
        print(f"   --> API全表示件数: {len(all_events_data)}件 OK")

        res_api_fav = client.get("/api/calendar-events?favorite_only=true")
        assert res_api_fav.status_code == 200
        fav_events_data = res_api_fav.json()
        assert any(ev["source_name"] == "お気に入り校" for ev in fav_events_data)
        assert not any(ev["source_name"] == "その他校" for ev in fav_events_data)
        print(f"   --> APIお気に入り限定表示件数: {len(fav_events_data)}件 OK")

        print("\n=== [カレンダーお気に入り表示切り替え機能の検証完了 大成功！] ===")
    finally:
        db.close()

if __name__ == "__main__":
    test_calendar_favorite_filter()
