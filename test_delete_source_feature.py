from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import Source, Event

def test_delete_source_feature():
    print("=== [巡回ソース解除（削除）機能 テスト] ===")
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    db = SessionLocal()
    try:
        # 既存のテスト用ソースがあればクリーンアップ
        old_sources = db.query(Source).filter(Source.source_id == "src_to_be_deleted").all()
        for s in old_sources:
            db.query(Event).filter(Event.source_id == s.id).delete()
            db.delete(s)
        db.commit()

        # 管理者でログイン
        client.post("/login", data={"username": "demo_user", "password": "password123"})

        # テスト用ソースと関連イベントを作成
        source = Source(
            source_id="src_to_be_deleted",
            category_id=1,
            name="削除対象校サンプル",
            type="school",
            url="http://example.com/del_test",
            schedule_interval_minutes=60,
            selectors_json="{}"
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        event = Event(
            source_id=source.id,
            title="削除対象イベント",
            url="http://example.com/del_event"
        )
        db.add(event)
        db.commit()
        deleted_source_id = source.id
        print(f"   --> テスト用ソース作成 (ID: {deleted_source_id}, 名前: {source.name}) OK")

        # 1. 管理画面 (/admin) に解除ボタンが存在することを確認
        res_admin = client.get("/admin")
        assert res_admin.status_code == 200
        assert '/admin/delete-source' in res_admin.text
        assert '解除' in res_admin.text
        print("   --> 管理画面 (/admin) の「解除」ボタン設置確認 OK")

        # 2. 巡回ソースの解除 API (POST /admin/delete-source) 実行
        res_del = client.post(
            "/admin/delete-source",
            data={"source_id": deleted_source_id},
            follow_redirects=True
        )
        assert res_del.status_code == 200
        print("   --> ソース解除 API 実行 (200 OK)")

        # 3. DBから対象ソースおよび関連イベントが削除されたか確認
        check_source = db.query(Source).filter(Source.id == deleted_source_id).first()
        assert check_source is None

        check_event = db.query(Event).filter(Event.source_id == deleted_source_id).first()
        assert check_event is None
        print("   --> DBより対象ソースおよび連動イベントのカスケード完全削除を確認 OK")

        print("\n=== [巡回ソース解除（削除）機能の全テスト大成功！] ===")

    finally:
        db.close()

if __name__ == "__main__":
    test_delete_source_feature()
