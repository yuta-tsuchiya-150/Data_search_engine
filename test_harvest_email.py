from app.models.schema import Event, Source
from app.notifier.email_service import EmailNotifier

def test_harvest_and_test_email():
    print("=== [TEST START] Harvest Email Notification Test ===")

    # 1. テストメール送信テスト
    test_result = EmailNotifier.send_test_email("master@example.com")
    assert test_result is True, "send_test_email should succeed (mock/safe mode)"
    print("✅ send_test_email test passed!")

    # 2. 回収イベントダイジェストメールテスト
    dummy_source1 = Source(id=101, name="慶應義塾幼稚舎")
    dummy_source2 = Source(id=102, name="早稲田実業学校初等部")

    dummy_events = [
        Event(
            id=1,
            source_id=101,
            source=dummy_source1,
            title="2027年度 第1回 学校説明会",
            event_date="2026-10-15",
            location="幼稚舎講堂",
            url="https://example.com/keio1"
        ),
        Event(
            id=2,
            source_id=101,
            source=dummy_source1,
            title="2027年度 入試願書配布開始",
            event_date="2026-09-20",
            location="事務室窓口",
            url="https://example.com/keio2"
        ),
        Event(
            id=3,
            source_id=102,
            source=dummy_source2,
            title="初等部 オープンキャンパス見学会",
            event_date="2026-10-22",
            location="国分寺キャンパス",
            url="https://example.com/waseda1"
        )
    ]

    harvest_result = EmailNotifier.notify_admin_harvest_report(dummy_events)
    assert harvest_result is True, "notify_admin_harvest_report should succeed"
    print("✅ notify_admin_harvest_report test passed with 3 dummy events across 2 schools!")

    # 0件時はFalseで静かに終了することを確認
    empty_result = EmailNotifier.notify_admin_harvest_report([])
    assert empty_result is False, "empty events should return False without sending"
    print("✅ empty events handled silently (no unnecessary emails)!")

    print("=== [TEST SUCCESS] All Email Notification Tests Passed! ===")

if __name__ == "__main__":
    test_harvest_and_test_email()
