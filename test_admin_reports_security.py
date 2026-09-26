from fastapi.testclient import TestClient
from app.main import app

def test_admin_reports_security():
    client = TestClient(app)

    # 1. 未ログインアクセス（ログイン画面へ303リダイレクト）
    res_unauth_list = client.get("/admin/reports", follow_redirects=False)
    assert res_unauth_list.status_code == 303
    assert "/login?next=/admin/reports" in res_unauth_list.headers["location"]

    res_unauth_detail = client.get("/admin/reports/20260926-01-education-business", follow_redirects=False)
    assert res_unauth_detail.status_code == 303
    assert "/login?next=/admin/reports/20260926-01-education-business" in res_unauth_detail.headers["location"]

    res_unauth_legacy = client.get("/report", follow_redirects=False)
    assert res_unauth_legacy.status_code == 303
    assert "/login?next=/admin/reports/20260926-01-education-business" in res_unauth_legacy.headers["location"]

    # 2. 一般ユーザーでのアクセス（is_admin=False: 404 でシャットアウト）
    client.cookies.set("current_user", "demo_parent")
    res_normal = client.get("/admin/reports")
    assert res_normal.status_code == 404, "Expected 404 for normal user access"

    # 3. 管理者ユーザーでのアクセス（is_admin=True: 200 OK で閲覧可能）
    client.cookies.set("current_user", "test")  # t1738315@gmail.com
    res_admin_list = client.get("/admin/reports")
    assert res_admin_list.status_code == 200
    assert "社内戦略レポート・AI討議アーカイブ" in res_admin_list.text
    assert "2026-09-26 #01" in res_admin_list.text
    assert "noindex" in res_admin_list.text

    res_admin_detail = client.get("/admin/reports/20260926-01-education-business")
    assert res_admin_detail.status_code == 200
    assert "子育て・受験・教育系 新規事業戦略レポート" in res_admin_detail.text
    assert "noindex" in res_admin_detail.text
    assert "2026-09-26 #01" in res_admin_detail.text

    # 旧/reportからリダイレクトされて閲覧できるか
    res_legacy_admin = client.get("/report", follow_redirects=False)
    assert res_legacy_admin.status_code == 302
    assert res_legacy_admin.headers["location"] == "/admin/reports/20260926-01-education-business"

    print("[SUCCESS] All admin report security & isolation tests passed successfully!")

if __name__ == "__main__":
    test_admin_reports_security()
