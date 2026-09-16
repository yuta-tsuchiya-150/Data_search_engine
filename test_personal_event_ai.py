import sys
from fastapi.testclient import TestClient
from app.main import app, get_db
from app.models.schema import User, Event

def test_personal_event_registration():
    client = TestClient(app)
    db = next(get_db())

    demo_user = db.query(User).filter(User.username == "demo_user").first()
    assert demo_user is not None, "Demo user should exist"

    # AIチャットに日程を含むメッセージを送信 (cookie付き)
    response = client.post(
        "/api/ai-chat",
        data={"query": "10月28日に伸芽会の秋期直前模試があります。カレンダーに登録して"},
        cookies={"current_user": demo_user.username}
    )
    assert response.status_code == 200
    res_json = response.json()
    print("AI Response Keys:", res_json.keys())
    print("Detected Event:", res_json.get("detected_event"))
    assert res_json["status"] == "ok"
    assert res_json.get("detected_event") is not None, "Detected event should be created"

    # カレンダーAPIで取得し、[マイ予定] のパープルカラーイベントが存在するか検証
    cal_res = client.get("/api/calendar-events", cookies={"current_user": demo_user.username})
    assert cal_res.status_code == 200
    cal_json = cal_res.json()
    print("Calendar JSON items count:", len(cal_json))
    personal_items = [item for item in cal_json if item.get("isPersonal") is True]
    print("Personal items count:", len(personal_items))
    assert len(personal_items) > 0, "Should contain at least one personal event"

    target_item = personal_items[0]
    assert "[マイ予定]" in target_item["title"]
    assert target_item["start"] == "2026-10-28"
    assert target_item["backgroundColor"] == "#8b5cf6"

    print("[SUCCESS] Personal event extraction & auto-registration test passed!")

if __name__ == "__main__":
    test_personal_event_registration()
