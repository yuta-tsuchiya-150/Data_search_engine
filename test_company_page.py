from fastapi.testclient import TestClient
from app.main import app

def test_company_page_rendering():
    client = TestClient(app)

    # 1. /company へのアクセステスト
    res = client.get("/company")
    assert res.status_code == 200
    html = res.text
    assert "日本資産運用機構" in html
    assert "運営会社情報" in html
    assert "会社概要" in html
    assert "Corporate Information" in html
    assert "DataSearchHub" in html

    # 2. /about からのリダイレクトテスト
    res_about = client.get("/about", follow_redirects=False)
    assert res_about.status_code == 301
    assert res_about.headers["location"] == "/company"

    # 3. トップページおよびフッターのリンク確認
    res_home = client.get("/")
    assert res_home.status_code == 200
    assert 'href="/company"' in res_home.text
    assert "会社概要（日本資産運用機構）" in res_home.text

    # 4. プライバシーポリシーページ内のリンク確認
    res_privacy = client.get("/privacy")
    assert res_privacy.status_code == 200
    assert 'href="/company"' in res_privacy.text

    print("[SUCCESS] All company page & navigation tests passed successfully!")

if __name__ == "__main__":
    test_company_page_rendering()
