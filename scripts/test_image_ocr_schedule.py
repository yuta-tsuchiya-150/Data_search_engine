import os
import sys
sys.path.insert(0, os.path.abspath("."))
import io
from app.ai_chat.ai_advisor import OjukenAIAdvisor
from app.main import app, SessionLocal
from app.models.schema import User, Event, Source
from fastapi.testclient import TestClient

def create_sample_handout_image():
    # 1x1 valid PNG bytes
    return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82'

def test_extract_events():
    # Test JSON array parsing
    ai_json_sample = """
画像から以下の予定を検出しました。
```json
[
  {"title": "第3回 秋期公開模試", "event_date": "2026-10-18", "location": "伸芽会 渋谷校", "content": "持ち物: 筆記用具、上履き"},
  {"title": "保護者面接ガイダンス", "event_date": "2026-11-03", "location": "伸芽会 本部", "content": "服装: スーツ着用"}
]
```
当日のアドバイスをお伝えします。
"""
    events = OjukenAIAdvisor.extract_events_from_text("プリント読み取り", ai_json_sample)
    print(f"Extracted events: {events}")
    assert len(events) == 2
    assert events[0]["title"] == "第3回 秋期公開模試"
    assert events[0]["event_date"] == "2026-10-18"
    assert events[1]["title"] == "保護者面接ガイダンス"
    assert events[1]["event_date"] == "2026-11-03"
    print("extract_events_from_text test passed!")

def test_api_with_client():
    client = TestClient(app)
    img_bytes = create_sample_handout_image()

    # Login as demo_user
    res_login = client.post("/login", data={"username": "demo_user", "password": "password123"}, follow_redirects=False)
    cookies = res_login.cookies

    # Send /api/ai-chat with image
    files = {
        "image": ("handout_sample.png", img_bytes, "image/png")
    }
    data = {
        "query": "このプリントの予定をマイカレンダーに入れて"
    }
    res = client.post("/api/ai-chat", data=data, files=files, cookies=cookies)
    print(f"API Response status: {res.status_code}")
    res_data = res.json()
    print("API Answer preview:", res_data.get("answer")[:200])
    assert res.status_code == 200
    print("API Test with image passed!")

if __name__ == "__main__":
    test_extract_events()
    test_api_with_client()
