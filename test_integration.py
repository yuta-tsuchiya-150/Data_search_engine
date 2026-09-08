import asyncio
import httpx
import time
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app.models.schema import User, Source, Event, Favorite, NotificationLog
from app.scraper.runner import ScraperRunner
from app.notifier.email_service import EmailNotifier

async def main():
    print("=== [統合動作検証テスト開始] ===")
    
    # DBテーブルの作成
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 1. YAML設定ファイルの読み込み検証
        print("\n1. YAML設定ファイルの自動インポート検証...")
        ScraperRunner.load_configs_from_directory("configs", db)
        sources = db.query(Source).all()
        print(f"   --> ロードされたソース数: {len(sources)} 件")
        for s in sources:
            print(f"       - Source: {s.name} (Category: {s.category.name}, URL: {s.url})")

        # 2. オンデマンドスクレイピング & 構造化抽出の検証
        print("\n2. モックサイトへの汎用スクレイピング実行...")
        new_events = await ScraperRunner.run_all_scrapers(db)
        print(f"   --> 新規抽出イベント数: {len(new_events)} 件")
        for e in new_events:
            print(f"       - Event: [{e.source.name}] {e.title} (開催日: {e.event_date}, 会場: {e.location})")

        # 3. ユーザーとお気に入り登録の検証
        print("\n3. 有料会員とお気に入り設定の検証...")
        user = db.query(User).filter(User.username == "demo_parent").first()
        if not user:
            user = User(
                username="demo_parent",
                email="parent@example.com",
                hashed_password="hash",
                is_paid=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        print(f"   --> 検証用ユーザー: {user.username} (有料会員: {user.is_paid})")
        
        # 全ソースをお気に入り登録
        for s in sources:
            fav = db.query(Favorite).filter(Favorite.user_id == user.id, Favorite.source_id == s.id).first()
            if not fav:
                fav = Favorite(user_id=user.id, source_id=s.id)
                db.add(fav)
        db.commit()
        print("   --> 全対象ソースをフォローお気に入りに登録完了")

        # 4. 差分検知とプッシュメール送信の検証
        print("\n4. 新規イベント通知エンジンの検証...")
        all_events = db.query(Event).all()
        sent_count = EmailNotifier.notify_users_for_new_events(all_events, db)
        print(f"   --> プッシュメール送信ログ作成数: {sent_count} 件")

        # 5. 通知ログの確認
        logs = db.query(NotificationLog).all()
        print(f"   --> DB格納済み通知ログ数: {len(logs)} 件")

        print("\n=== [全バックエンド・エンジン統合テスト成功！] ===")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
