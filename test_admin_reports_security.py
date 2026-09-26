from fastapi.testclient import TestClient
from app.main import app
from app.reports_registry import get_all_reports

def test_admin_reports_full_workflow():
    client = TestClient(app)

    # 1. 未ログインアクセス（ログイン画面へ303リダイレクト）
    res_unauth_list = client.get("/admin/reports", follow_redirects=False)
    assert res_unauth_list.status_code == 303
    assert "/login?next=/admin/reports" in res_unauth_list.headers["location"]

    res_unauth_new = client.get("/admin/reports/new", follow_redirects=False)
    assert res_unauth_new.status_code == 303

    # 2. 一般ユーザーでのアクセス（is_admin=False: 404 でシャットアウト）
    client.cookies.set("current_user", "demo_parent")
    res_normal = client.get("/admin/reports")
    assert res_normal.status_code == 404, "Expected 404 for normal user access"

    res_normal_new = client.get("/admin/reports/new")
    assert res_normal_new.status_code == 404

    # 3. 管理者ユーザーでのアクセス（is_admin=True: 200 OK で閲覧可能）
    client.cookies.set("current_user", "test")  # 管理者
    res_admin_list = client.get("/admin/reports")
    assert res_admin_list.status_code == 200
    assert "社内戦略レポート・AI討議アーカイブ" in res_admin_list.text
    assert "新規AI討議レポートを生成" in res_admin_list.text

    # 新規作成フォーム画面
    res_admin_new = client.get("/admin/reports/new")
    assert res_admin_new.status_code == 200
    assert "AIエージェントチーム討議 ＆ 戦略レポート自動生成" in res_admin_new.text
    assert "検討したいお題・ビジネスのテーマ" in res_admin_new.text

    # 4. レポート生成実行テスト
    form_data = {
        "topic": "テスト自動化：放課後等デイサービスの空き枠リアルタイム速報サービス",
        "constraints": "初期費用50万円以内 / 実店舗なし / 資格不要",
        "team_type": "bizdev"
    }
    res_gen = client.post("/admin/reports/generate", data=form_data, follow_redirects=False)
    assert res_gen.status_code == 303
    created_url = res_gen.headers["location"]
    assert "/admin/reports/" in created_url
    created_id = created_url.split("/admin/reports/")[1]

    # 5. 生成されたレポートの詳細ページ閲覧
    res_detail = client.get(f"/admin/reports/{created_id}")
    assert res_detail.status_code == 200
    assert "放課後等デイサービス" in res_detail.text
    assert "厳守制約条件・禁止事項クリア確認" in res_detail.text
    assert "目次（Table of Contents）" in res_detail.text

    # 6. Markdownファイルのダウンロードテスト
    res_dl = client.get(f"/admin/reports/{created_id}/download")
    assert res_dl.status_code == 200
    assert "attachment;" in res_dl.headers.get("content-disposition", "")
    assert res_dl.headers["content-type"].startswith("text/markdown")
    assert len(res_dl.text) > 100

    # 7. レポート削除テスト
    res_del = client.post(f"/admin/reports/{created_id}/delete", follow_redirects=False)
    assert res_del.status_code == 303
    assert res_del.headers["location"] == "/admin/reports?msg=deleted"

    # 削除後の確認
    res_check = client.get(f"/admin/reports/{created_id}")
    assert res_check.status_code == 404

    print("[SUCCESS] All AI Agent Discussion & Strategy Report tests passed with flying colors!")

if __name__ == "__main__":
    test_admin_reports_full_workflow()
