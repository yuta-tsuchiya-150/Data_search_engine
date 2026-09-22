import sqlite3
import os
import sys

def purge_all_mock_data(db_path: str):
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print(f"=== Starting Thorough Mock & Dummy Data Purge: {db_path} ===")

    # 1. 削除対象のソースを抽出
    c.execute("""
        SELECT id, source_id, name, url FROM sources
        WHERE (
            name LIKE '%その他校%' OR
            name LIKE '%お気に入り校%' OR
            name LIKE '%サンプル%' OR
            name LIKE '%sample%' OR
            name LIKE '%プリセット%' OR
            url LIKE '%127.0.0.1%' OR
            url LIKE '%localhost%' OR
            url LIKE '%google.com/search%' OR
            (url LIKE '%example.com%' AND source_id != 'my_personal_events') OR
            source_id LIKE 'test_%' OR
            source_id IN ('src_fav_school', 'src_other_school')
        )
    """)
    target_sources = c.fetchall()
    target_source_ids = [s[0] for s in target_sources]

    print(f"Found {len(target_sources)} mock/dummy sources to purge:")
    for s in target_sources:
        print(f"  - ID: {s[0]}, SID: {s[1]}, Name: {s[2]}, URL: {s[3]}")

    if target_source_ids:
        placeholders = ",".join("?" for _ in target_source_ids)
        c.execute(f"DELETE FROM notification_logs WHERE event_id IN (SELECT id FROM events WHERE source_id IN ({placeholders}))", target_source_ids)
        c.execute(f"DELETE FROM favorites WHERE source_id IN ({placeholders})", target_source_ids)
        c.execute(f"DELETE FROM events WHERE source_id IN ({placeholders})", target_source_ids)
        c.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", target_source_ids)
        print(f"  Purged {len(target_source_ids)} sources and all associated events/favorites.")

    # 2. その他、タイトルやURLにモック・検索URLを含む残存イベント（個人予定以外）の削除
    c.execute("""
        DELETE FROM events
        WHERE user_id IS NULL AND (
            title LIKE '%その他校%' OR
            title LIKE '%お気に入り校%' OR
            title LIKE '%サンプル%' OR
            title LIKE '%sample%' OR
            title LIKE '%[Example]%' OR
            url LIKE '%127.0.0.1%' OR
            url LIKE '%localhost%' OR
            url LIKE '%example.com%' OR
            url LIKE '%google.com/search%'
        )
    """)
    deleted_events_count = c.rowcount
    if deleted_events_count > 0:
        print(f"Purged {deleted_events_count} stray mock/search-url events.")

    # 3. 孤立したイベントの削除
    c.execute("DELETE FROM events WHERE source_id NOT IN (SELECT id FROM sources) AND user_id IS NULL")
    orphaned_events = c.rowcount
    if orphaned_events > 0:
        print(f"Purged {orphaned_events} orphaned events.")

    conn.commit()

    # 残存チェック
    c.execute("SELECT count(*) FROM sources")
    rem_sources = c.fetchone()[0]
    c.execute("SELECT count(*) FROM events WHERE user_id IS NULL")
    rem_public_events = c.fetchone()[0]
    print(f"Purge complete! Remaining clean sources: {rem_sources}, Remaining public events: {rem_public_events}")

    conn.close()

if __name__ == "__main__":
    db_file = sys.argv[1] if len(sys.argv) > 1 else "data_search_engine.db"
    purge_all_mock_data(db_file)
