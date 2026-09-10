from fastapi.testclient import TestClient
from app.main import app, extract_group_name
from app.database import SessionLocal, engine, Base
from app.models.schema import User, Source, Favorite

def test_group_favorites():
    print("=== [学校・塾スマートグループ化 ＆ 一括お気に入り登録機能 テスト] ===")

    # 1. グループ名抽出ロジックの判定テスト
    print("\n1. グループ親名称抽出ロジック (extract_group_name) の検証...")
    assert extract_group_name("青山学院初等部 - 入試案内") == "青山学院初等部"
    assert extract_group_name("慶應義塾幼稚舎 (サンプル)") == "慶應義塾幼稚舎"
    assert extract_group_name("こぐま会 - 模試日程") == "こぐま会"
    print("   --> グループ抽出ロジック 正常確認")

    Base.metadata.create_all(bind=engine)
    db_init = SessionLocal()
    from app.scraper.runner import ScraperRunner
    ScraperRunner.load_configs_from_directory("configs", db_init)
    db_init.close()

    client = TestClient(app)

    # 2. 学校一覧画面 (GET /schools) のグループ化データ検証
    print("\n2. 学校一覧画面 (GET /schools) のグループ表示検証...")
    res_schools = client.get("/schools")
    assert res_schools.status_code == 200
    assert "関係" in res_schools.text
    print("   --> 学校・塾一覧画面のグループ化表示 200 OK")

    # 3. ユーザーログイン ＆ グループ一括お気に入り登録テスト
    print("\n3. 『青山学院初等部関係』グループ一括お気に入り登録 API テスト...")
    # まずユーザーを作成
    db_u = SessionLocal()
    user_test = db_u.query(User).filter(User.username == "demo_user").first()
    if not user_test:
        from app.auth import hash_password
        user_test = User(username="demo_user", email="demo@example.com", hashed_password=hash_password("password123"))
        db_u.add(user_test)
        db_u.commit()
    else:
        db_u.query(Favorite).filter(Favorite.user_id == user_test.id).delete()
        db_u.commit()
    db_u.close()

    client.post("/login", data={"username": "demo_user", "password": "password123"})

    res_group_fav = client.post("/toggle-favorite-group", data={"group_name": "青山学院初等部"}, follow_redirects=True)
    assert res_group_fav.status_code == 200
    print("   --> 青山学院初等部関係グループの一括登録完了 200 OK")

    # DBでお気に入り件数を確認
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "demo_user").first()
        favs = db.query(Favorite).filter(Favorite.user_id == user.id).all()
        fav_source_names = [f.source.name for f in favs]
        print(f"   --> ユーザーが現在一括お気に入り登録中の全ソース: {fav_source_names}")
        assert any("青山" in name for name in fav_source_names)

        # 4. マイページでのグループ表示確認
        res_dash = client.get("/dashboard")
        assert res_dash.status_code == 200
        assert "青山学院初等部関係" in res_dash.text
        print("   --> マイページでの『青山学院初等部関係』表示確認 200 OK")

        print("\n=== [スマートグループ化 ＆ 一括お気に入り登録機能の全テスト大成功！] ===")

    finally:
        db.close()

if __name__ == "__main__":
    test_group_favorites()
