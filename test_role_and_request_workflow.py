from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import User, SourceRequest
from app.auth import hash_password

def test_role_and_request_workflow():
    print("=== [ユーザー役割分離 ＆ 未登録ページ追加リクエスト機能 テスト] ===")
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    db = SessionLocal()
    try:
        # 1. 一般ユーザーと管理者ユーザーを作成
        normal_u = db.query(User).filter(User.username == "test_normal_user").first()
        if not normal_u:
            normal_u = User(username="test_normal_user", email="normal@example.com", hashed_password=hash_password("pass123"), is_admin=False)
            db.add(normal_u)

        admin_u = db.query(User).filter(User.username == "test_admin_user").first()
        if not admin_u:
            admin_u = User(username="test_admin_user", email="admin@example.com", hashed_password=hash_password("pass123"), is_admin=True)
            db.add(admin_u)

        db.commit()
        db.refresh(normal_u)
        db.refresh(admin_u)

        # 事前に過去のテストリクエストをクリーンアップ
        req_url = "http://127.0.0.1:8080/schools/aoyama_gakuin.html"
        db.query(SourceRequest).filter(SourceRequest.user_id == normal_u.id, SourceRequest.url == req_url).delete()
        db.commit()

        # 2. 一般ユーザーでログイン
        client.post("/login", data={"username": "test_normal_user", "password": "pass123"})

        # 一般ユーザーによる管理者画面 (/admin) へのアクセス拒否をテスト
        res_admin_deny = client.get("/admin", follow_redirects=False)
        assert res_admin_deny.status_code in [302, 303]
        assert res_admin_deny.headers.get("location") == "/dashboard"
        print("   --> 一般ユーザーの管理者画面 (/admin) アクセス制御拒否・リダイレクト確認 OK")

        # 一般ユーザーによる追加リクエスト送信
        req_url = "http://127.0.0.1:8080/schools/aoyama_gakuin.html"
        res_req = client.post("/request-source", data={"target_url": req_url, "note": "青山学院追加の希望"}, follow_redirects=True)
        assert res_req.status_code == 200
        print("   --> 一般ユーザーによる追加リクエスト送信 (200 OK)")

        # マイページ (/dashboard) での申請確認
        res_dash = client.get("/dashboard")
        assert res_dash.status_code == 200
        assert "青山学院追加の希望" in res_dash.text
        assert "審査・巡回登録中" in res_dash.text
        print("   --> マイページ (/dashboard) での申請進捗（審査中）確認 OK")

        # DBで申請レコードを取得
        req_obj = db.query(SourceRequest).filter(SourceRequest.user_id == normal_u.id, SourceRequest.url == req_url).first()
        assert req_obj is not None
        assert req_obj.status == "pending"

        # 3. 管理者ユーザーでログイン
        client.post("/login", data={"username": "test_admin_user", "password": "pass123"})

        # 管理者画面 (/admin) アクセス権限確認
        res_admin_allow = client.get("/admin")
        assert res_admin_allow.status_code == 200
        assert "ユーザーからの追加リクエスト一覧" in res_admin_allow.text
        assert "青山学院追加の希望" in res_admin_allow.text
        print("   --> 管理者画面 (/admin) アクセス許可 ＆ 未処理リクエスト表示確認 OK")

        # 管理者によるリクエスト承認 (POST /admin/update-request-status)
        res_approve = client.post("/admin/update-request-status", data={"request_id": req_obj.id, "status_val": "approved"}, follow_redirects=True)
        assert res_approve.status_code == 200

        # ステータス更新検証
        db.refresh(req_obj)
        assert req_obj.status == "approved"
        print("   --> 管理者によるリクエスト承認・ステータス更新 (approved) 確認 OK")

        # 一般ユーザーで再度ログインし、マイページで「承認・登録完了」バッジを確認
        client.post("/login", data={"username": "test_normal_user", "password": "pass123"})
        res_dash_approved = client.get("/dashboard")
        assert res_dash_approved.status_code == 200
        assert "承認・登録完了" in res_dash_approved.text
        print("   --> 一般ユーザーマイページでの『承認・登録完了』バッジ表示確認 OK")

        print("\n=== [ユーザー役割分離 ＆ 未登録ページ追加リクエスト機能の全テスト大成功！] ===")

    finally:
        db.close()

if __name__ == "__main__":
    test_role_and_request_workflow()
