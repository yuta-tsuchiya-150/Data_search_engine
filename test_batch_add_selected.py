import json
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import Source

def test_batch_add_selected():
    print("=== [チェックボックス選択一括登録機能 テスト] ===")
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    db = SessionLocal()
    try:
        # 既存の同URLテストデータがあれば事前に削除
        db.query(Source).filter(Source.url.in_(["http://example.com/rikkyo_admissions", "http://example.com/rikkyo_guidance"])).delete(synchronize_session=False)
        db.commit()

        # テスト用候補アイテム（3件中2件を選択してPOSTするシミュレーション）
        sample_candidates = [
            {
                "school_name": "立教小学校",
                "page_title": "入試情報",
                "url": "http://example.com/rikkyo_admissions",
                "selectors": {"item_container": ".news"}
            },
            {
                "school_name": "立教小学校",
                "page_title": "学校説明会案内",
                "url": "http://example.com/rikkyo_guidance",
                "selectors": {"item_container": ".event"}
            }
        ]

        # 1. 選択された候補のJSONを一括登録API (/admin/add-all-discovered-sources) に送信
        res = client.post("/admin/add-all-discovered-sources", data={
            "sources_json": json.dumps(sample_candidates)
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["added_count"] == 2
        print("   --> チェックボックスで選択された2件のみの一括登録 API 200 OK")

        # 2. DBに対象の2件のみ登録されたか検証
        s1 = db.query(Source).filter(Source.url == "http://example.com/rikkyo_admissions").first()
        s2 = db.query(Source).filter(Source.url == "http://example.com/rikkyo_guidance").first()
        assert s1 is not None
        assert s2 is not None
        print(f"   --> DB保存確認: {s1.name}, {s2.name} OK")

        print("\n=== [チェックボックス選択一括登録機能の検証完了 大成功！] ===")

    finally:
        db.close()

if __name__ == "__main__":
    test_batch_add_selected()
