import json
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import Source, Event

def test_batch_add_api():
    print("=== [検出候補 一括自動登録 API テスト] ===")

    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    # 模擬候補データ2件
    mock_candidates = [
        {
            "school_name": "青山学院初等部",
            "page_title": "入試案内・説明会情報",
            "url": "http://127.0.0.1:8080/schools/aoyama_gakuin.html",
            "selectors": {"item_container": ".news-item", "title": ".news-title", "date": ".news-date"}
        },
        {
            "school_name": "慶應義塾幼稚舎",
            "page_title": "学校説明会と見学会",
            "url": "http://127.0.0.1:8080/schools/keio_yochisha.html",
            "selectors": {"item_container": ".news-item", "title": ".news-title", "date": ".news-date"}
        }
    ]

    print("\n1. 一括登録 API POST /admin/add-all-discovered-sources の呼出...")
    res = client.post("/admin/add-all-discovered-sources", data={
        "sources_json": json.dumps(mock_candidates)
    })
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["status"] == "ok"
    print(f"   --> 一括登録完了件数: {res_data['added_count']} 件")

    print("\n=== [一括登録機能の検証成功！] ===")

if __name__ == "__main__":
    test_batch_add_api()
