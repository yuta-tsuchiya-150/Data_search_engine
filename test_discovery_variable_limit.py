from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base

def test_discovery_variable_limit():
    print("=== [自動URL検出 表示件数可変（5~30件5件刻み）機能 テスト] ===")
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    target_url = "http://127.0.0.1:8080/schools/aoyama_gakuin.html"

    # 1. limit=5 でのリクエスト
    res_5 = client.post("/admin/discover-sources", data={"target_url": target_url, "limit": 5})
    assert res_5.status_code == 200
    results_5 = res_5.json()["results"]
    assert len(results_5) <= 5
    print(f"   --> limit=5 指定時: {len(results_5)}件 取得 OK")

    # 2. limit=20 でのリクエスト
    res_20 = client.post("/admin/discover-sources", data={"target_url": target_url, "limit": 20})
    assert res_20.status_code == 200
    results_20 = res_20.json()["results"]
    assert len(results_20) <= 20
    print(f"   --> limit=20 指定時: {len(results_20)}件 取得 OK")

    print("\n=== [自動URL検出 表示件数可変（5~30件）機能の検証完了 大成功！] ===")

if __name__ == "__main__":
    test_discovery_variable_limit()
