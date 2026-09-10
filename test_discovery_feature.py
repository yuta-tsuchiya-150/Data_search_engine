import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, engine, Base
from app.models.schema import Source, Event

async def run_test():
    print("=== [自動URL発見＆お受験キーワード選別エンジン テスト] ===")

    Base.metadata.create_all(bind=engine)
    client = TestClient(app)

    target_url = "http://127.0.0.1:8080/schools/aoyama_gakuin.html"

    # 1. ディスカバリー API の呼び出し (URLのみの入力)
    print("\n1. URLのみからの学校名自動抽出 ＆ 関連ページ自動検出 API テスト...")
    res_disc = client.post("/admin/discover-sources", data={
        "target_url": target_url
    })
    assert res_disc.status_code == 200
    data = res_disc.json()
    assert data["status"] == "ok"
    results = data["results"]
    print(f"   --> 検出・選別された関連ページ数: {len(results)} 件")
    assert len(results) > 0
    candidate = results[0]
    school_name = candidate['school_name']
    assert school_name != ""
    print(f"       - 自動抽出された学校名: {school_name}")
    print(f"       - 選別ページタイトル: {candidate['page_title']}")
    print(f"       - 判定キーワード: {candidate['matched_keywords']}")
    print(f"       - 自動生成CSSセレクター: {candidate['selectors']}")

    # 2. 自動選別されたソースのワンクリック登録 API テスト
    print("\n2. 選別ソースのワンクリック自動登録 API テスト...")
    res_add = client.post("/admin/add-discovered-source", data={
        "school_name": f"{school_name} - {candidate['page_title']}",
        "source_url": candidate['url'],
        "category_id": "elementary_school",
        "source_type": "school",
        "selectors_json": '{"item_container": ".news-item", "title": ".news-title", "date": ".news-date", "event_date": ".event-date", "location": ".event-location", "link": "a::attr(href)"}'
    }, follow_redirects=True)
    assert res_add.status_code == 200
    print("   --> ソースの自動登録および即時巡回が正常完了！")

    # 3. DBに新規登録されたか確認
    db = SessionLocal()
    try:
        added_source = db.query(Source).filter(Source.name.like(f"%{school_name}%")).first()
        assert added_source is not None
        print(f"   --> DBに保存されたソース名: {added_source.name}")
        events = db.query(Event).filter(Event.source_id == added_source.id).all()
        print(f"   --> 即時自動収集されたイベント件数: {len(events)} 件")
        for e in events:
            print(f"       - 収集イベント: {e.title} (開催日: {e.event_date})")

        print("\n=== [自動URL発見＆選別・登録エンジン全テスト大成功！] ===")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_test())
