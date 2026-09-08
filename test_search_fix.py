from fastapi.testclient import TestClient
from app.main import app

def test_empty_query_params():
    print("=== [絞り込み検索 空文字クエリ検証テスト] ===")
    client = TestClient(app)

    # 1. source_id が空文字 ?source_id=&q=&category=elementary_school
    res1 = client.get("/?q=&category=elementary_school&source_id=&event_type=all")
    assert res1.status_code == 200
    print("   --> 空文字 source_id= リクエスト: 200 OK (エラー解消を確認)")

    # 2. 有効な数値 source_id=1
    res2 = client.get("/?source_id=1")
    assert res2.status_code == 200
    print("   --> 数値 source_id=1 リクエスト: 200 OK")

    # 3. カレンダーAPIでの空文字 source_id=
    res3 = client.get("/api/calendar-events?source_id=")
    assert res3.status_code == 200
    print("   --> カレンダーAPI 空文字 source_id= リクエスト: 200 OK")

    print("\n=== [絞り込み検索エラーは完全に修正されました！] ===")

if __name__ == "__main__":
    test_empty_query_params()
