import os
import asyncio
import json
from app.database import engine, Base, SessionLocal
from app.models.schema import Source, Event, Category, AISelfHealingLog
from app.scraper.self_healing_agent import AISelfHealingAgent

async def run_test():
    print("=== [TEST START] AISelfHealingAgent Feature Test ===")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        cat = db.query(Category).first()
        if not cat:
            cat = Category(category_id="test_cat", name="テストカテゴリ")
            db.add(cat)
            db.commit()
            db.refresh(cat)

        # 1. 意図的に古い/壊れたセレクタを持つテスト用Sourceを作成
        test_source = db.query(Source).filter(Source.source_id == "test_healing_school").first()
        if not test_source:
            test_source = Source(
                source_id="test_healing_school",
                category_id=cat.id,
                name="テスト小学校（リニューアル校）",
                type="school",
                url="https://example.com/test_school",
                selectors_json=json.dumps({
                    "item": ".broken-old-class",
                    "title": ".broken-title",
                    "date": ".broken-date"
                })
            )
            db.add(test_source)
            db.commit()
            db.refresh(test_source)

        # 2. リニューアルされたHTML構造のサンプル（セレクタが .event-card-item に変わった）
        mock_new_html = """
        <!DOCTYPE html>
        <html>
        <head><title>テスト小学校 イベント情報</title></head>
        <body>
            <main>
                <h1>新着イベント一覧</h1>
                <div class="event-card-item">
                    <h3 class="event-heading">2027年度 第1回 学校説明会・公開授業</h3>
                    <span class="event-schedule">2026年10月15日(木) 10:00〜</span>
                    <p class="event-detail">本校講堂にて初等部教育の特色と2027年度入試要項をご説明します。</p>
                    <a class="detail-link" href="https://example.com/test_school/event1">詳細を見る</a>
                </div>
                <div class="event-card-item">
                    <h3 class="event-heading">秋期 秋の体験学習フェスティバル</h3>
                    <span class="event-schedule">2026年11月03日(祝)</span>
                    <p class="event-detail">年中・年長児対象の体験プログラムです。</p>
                    <a class="detail-link" href="https://example.com/test_school/event2">お申し込み</a>
                </div>
            </main>
        </body>
        </html>
        """

        print("Triggering attempt_heal_source...")
        # 3. 自律修復エージェントを実行
        healed_events = await AISelfHealingAgent.attempt_heal_source(
            source=test_source,
            html_content=mock_new_html,
            db=db,
            reason="テスト用ゼロ件検知 (0 items matched)"
        )

        print(f"Healed events count: {len(healed_events)}")

        # 4. DB内の修復ログを確認
        log = db.query(AISelfHealingLog).filter(AISelfHealingLog.source_id == test_source.id).order_by(AISelfHealingLog.created_at.desc()).first()
        assert log is not None, "AISelfHealingLog should be created in DB!"
        print(f"✅ Self-healing log verified: ID={log.id}, Status={log.status}, Reason={log.reason}, Events={log.events_count}")
        print(f"✅ Log Details:\n{log.details}")

        # 5. ソースのセレクタが更新されたか確認
        db.refresh(test_source)
        print(f"✅ Source selectors_json after heal: {test_source.selectors_json}")

        print("=== [TEST SUCCESS] AISelfHealingAgent Test Completed Successfully! ===")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_test())
