import sys
from fastapi.testclient import TestClient
from app.main import app

def test_home_page_rendering():
    client = TestClient(app)
    
    # 未ログイン状態でトップページにアクセス
    response = client.get("/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    html = response.text
    
    # 誘導テキスト・セクションキーの存在確認
    assert "無料会員登録する" in html, "Register CTA button not found"
    assert "ログイン" in html, "Login button not found"
    assert "会員サービス" in html, "Member service section title not found"
    assert "AIお受験コンサルタント" in html, "Benefit 1 title not found"
    assert "マイリスト＆専用カレンダー" in html, "Benefit 2 title not found"
    assert "今すぐ無料で会員登録して機能を利用する" in html, "Bottom CTA button not found"

    print("[SUCCESS] All home page CTA & registration incentive tests passed successfully!")

if __name__ == "__main__":
    test_home_page_rendering()
