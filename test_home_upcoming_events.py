import sys
from fastapi.testclient import TestClient
from app.main import app

def test_home_page_upcoming_events_metric():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    html = response.text
    # 「収集済みイベント数」から「本日以降のイベント数」に変更されたことの検証
    assert "本日以降のイベント数" in html, "Upcoming events label not found on home page"
    assert "収集済みイベント数" not in html, "Deprecated collected events label still present"

    print("[SUCCESS] Home page upcoming events metric test passed successfully!")

if __name__ == "__main__":
    test_home_page_upcoming_events_metric()
