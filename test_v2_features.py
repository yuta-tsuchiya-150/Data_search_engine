import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import Source, Event

def test_v2_updates():
    print("=== [DataSearchHub v2 コア機能自動検証テスト] ===")

    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    # 1. 検索・フィルター機能のテスト
    print("\n1. 検索・絞り込み機能の検証...")
    res_home = client.get("/")
    assert res_home.status_code == 200
    print("   --> TOPデータ一覧画面 200 OK")

    res_search = client.get("/?q=説明会")
    assert res_search.status_code == 200
    print("   --> キーワード『説明会』での検索フィルター 200 OK")

    res_filter_type = client.get("/?event_type=school")
    assert res_filter_type.status_code == 200
    print("   --> イベント種別『小学校』での絞り込み 200 OK")

    # 2. カレンダー機能 ＆ 詳細ポップアップ用 API のテスト
    print("\n2. インタラクティブカレンダー API の検証...")
    res_cal_page = client.get("/calendar")
    assert res_cal_page.status_code == 200
    print("   --> 月間カレンダー画面 200 OK")

    res_cal_api = client.get("/api/calendar-events")
    assert res_cal_api.status_code == 200
    events = res_cal_api.json()
    print(f"   --> カレンダー取得イベント数: {len(events)} 件")
    assert len(events) > 0
    first_event = events[0]
    print(f"       - イベントタイトル: {first_event['title']}")
    print(f"       - 開催日: {first_event['start']}")
    print(f"       - モーダル用詳細テキスト: {first_event['content'][:40]}...")
    assert "source_name" in first_event
    assert "content" in first_event

    # 3. データ収集設定（YAMLルール視覚化）画面のテスト
    print("\n3. 汎用エンジン設定ビジュアルビューの検証...")
    client.post("/login", data={"username": "demo_user", "password": "password123"})
    res_admin = client.get("/admin")
    assert res_admin.status_code == 200
    assert "データ収集エンジン" in res_admin.text
    print("   --> YAML抽出ルールのビジュアルカード表示 200 OK")

    print("\n=== [全3項目の改修機能テストが完全にパスいたしました！] ===")

if __name__ == "__main__":
    test_v2_updates()
