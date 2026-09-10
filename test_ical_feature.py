from fastapi.testclient import TestClient
from app.main import app

def test_ical_export_features():
    print("=== [Googleカレンダー連携 ＆ iCal (.ics) 出力機能 テスト] ===")
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

    # 1. 単一イベント iCal (.ics) ダウンロード API
    print("\n1. 単一イベント .ics ダウンロード API の検証...")
    res_single = client.get(f"/events/{event.id}/ical")
    assert res_single.status_code == 200
    assert "text/calendar" in res_single.headers["content-type"]
    assert "BEGIN:VCALENDAR" in res_single.text
    assert "BEGIN:VEVENT" in res_single.text
    assert "SUMMARY:" in res_single.text
    assert "END:VCALENDAR" in res_single.text
    print("   --> 単一イベント .ics ファイル正常生成 200 OK")

    # 2. 一括マイカレンダー .ics ダウンロード API
    print("\n2. 一括マイカレンダー .ics ダウンロード API の検証...")
    res_feed = client.get("/api/user-calendar-feed.ics")
    assert res_feed.status_code == 200
    assert "my_favorites_calendar.ics" in res_feed.headers["content-disposition"]
    assert "BEGIN:VCALENDAR" in res_feed.text
    print("   --> 一括 .ics カレンダーフィード正常生成 200 OK")

    # 3. カレンダーAPIでの google_calendar_url の検証
    print("\n3. カレンダーAPIにおける Google カレンダーダイレクトURL生成の検証...")
    res_api = client.get("/api/calendar-events")
    assert res_api.status_code == 200
    events = res_api.json()
    assert len(events) > 0
    first_event = events[0]
    assert "google_calendar_url" in first_event
    print(f"   --> 生成された Google カレンダー登録URL: {first_event['google_calendar_url'][:60]}...")

    print("\n=== [Googleカレンダー連携 (iCal出力) の全テストが完璧にパスいたしました！] ===")

if __name__ == "__main__":
    test_ical_export_features()
