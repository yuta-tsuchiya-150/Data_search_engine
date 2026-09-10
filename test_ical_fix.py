from fastapi.testclient import TestClient
from app.main import app

def test_ical_id_fix():
    print("=== [iCal (.ics) ボタン修正検証テスト] ===")
    client = TestClient(app)

    from app.database import SessionLocal, engine, Base
    from app.models.schema import Source, Event
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    event = db.query(Event).first()
    if not event:
        source = db.query(Source).first()
        if not source:
            source = Source(source_id="src_ical_test", category_id=1, name="iCalテスト校", type="school", url="http://example.com/ical", schedule_interval_minutes=60, selectors_json="{}")
            db.add(source)
            db.commit()
            db.refresh(source)
        event = Event(source_id=source.id, title="iCalテストイベント", url="http://example.com/event", event_date="2026-10-10")
        db.add(event)
        db.commit()
        db.refresh(event)
    db.close()

    # 1. 正常な ID での呼び出し
    res1 = client.get(f"/events/{event.id}/ical")
    assert res1.status_code == 200
    assert "BEGIN:VCALENDAR" in res1.text
    print("   --> 正常ID /events/1/ical : 200 OK (.ics ファイル取得成功)")

    # 2. 不正な ID (undefined) での呼び出し時のエラーハンドリング
    res2 = client.get("/events/undefined/ical")
    assert res2.status_code == 400
    print("   --> undefined パラメータ /events/undefined/ical : 400 Bad Request (エラーハンドリング成功)")

    # 3. カレンダー用 API のイベントIDプロパティ確認
    res3 = client.get("/api/calendar-events")
    assert res3.status_code == 200
    events = res3.json()
    assert len(events) > 0
    assert "id" in events[0]
    assert "event_id" in events[0]
    print(f"   --> カレンダーAPIのIDプロパティ: id='{events[0]['id']}', event_id={events[0]['event_id']}")

    print("\n=== [iCalボタンのエラーは完全に修復されました！] ===")

if __name__ == "__main__":
    test_ical_id_fix()
