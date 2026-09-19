import sqlite3
import os
import sys

def cleanup(db_path: str):
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print(f"=== Starting Database Cleanup for: {db_path} ===")

    # 1. 削除対象のソースを特定
    query = """
        SELECT id, source_id, name, url FROM sources
        WHERE (
            name LIKE '%サンプル%' OR
            name LIKE '%sample%' OR
            name LIKE '%プリセット%' OR
            url LIKE '%127.0.0.1%' OR
            url LIKE '%localhost%' OR
            (url LIKE '%example.com%' AND source_id != 'my_personal_events') OR
            source_id LIKE 'test_%' OR
            source_id IN ('src_fav_school', 'src_other_school')
        )
    """
    c.execute(query)
    target_sources = c.fetchall()
    target_source_ids = [s[0] for s in target_sources]

    print(f"Found {len(target_sources)} sample/mock sources to delete:")
    for s in target_sources:
        print(f"  - ID: {s[0]}, SID: {s[1]}, Name: {s[2]}, URL: {s[3]}")

    if target_source_ids:
        placeholders = ",".join("?" for _ in target_source_ids)

        # 関連する通知ログ削除
        c.execute(f"DELETE FROM notification_logs WHERE event_id IN (SELECT id FROM events WHERE source_id IN ({placeholders}))", target_source_ids)
        print(f"  Deleted associated notification logs.")

        # 関連するお気に入り削除
        c.execute(f"DELETE FROM favorites WHERE source_id IN ({placeholders})", target_source_ids)
        print(f"  Deleted associated favorites.")

        # 関連するイベント削除
        c.execute(f"DELETE FROM events WHERE source_id IN ({placeholders})", target_source_ids)
        print(f"  Deleted associated events.")

        # ソース本体削除
        c.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", target_source_ids)
        print(f"  Deleted {len(target_source_ids)} sources.")

    # 2. その他、タイトルやURLにサンプル・モックを含む残存イベント（個人予定以外）の削除
    c.execute("""
        DELETE FROM events
        WHERE user_id IS NULL AND (
            title LIKE '%サンプル%' OR
            title LIKE '%sample%' OR
            title LIKE '%[Example]%' OR
            url LIKE '%127.0.0.1%' OR
            url LIKE '%localhost%' OR
            url LIKE '%example.com%'
        )
    """)
    deleted_events_count = c.rowcount
    if deleted_events_count > 0:
        print(f"Deleted {deleted_events_count} stray sample events.")

    # 3. 孤立したイベントの削除
    c.execute("DELETE FROM events WHERE source_id NOT IN (SELECT id FROM sources) AND user_id IS NULL")
    orphaned_events = c.rowcount
    if orphaned_events > 0:
        print(f"Deleted {orphaned_events} orphaned events.")

    conn.commit()

    # 結果確認
    c.execute("SELECT count(*) FROM sources")
    rem_sources = c.fetchone()[0]
    c.execute("SELECT count(*) FROM events")
    rem_events = c.fetchone()[0]
    print(f"Cleanup finished! Remaining sources: {rem_sources}, Remaining events: {rem_events}")

    conn.close()

if __name__ == "__main__":
    db_file = sys.argv[1] if len(sys.argv) > 1 else "data_search_engine.db"
    cleanup(db_file)
