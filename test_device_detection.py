import sys
from fastapi.testclient import TestClient
from app.main import app
from app.device_helper import is_mobile_device
from fastapi import Request

def test_device_detection_logic():
    client = TestClient(app)

    # 1. PC User-Agent でのアクセステスト
    pc_headers = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    res_pc = client.get("/", headers=pc_headers)
    assert res_pc.status_code == 200
    html_pc = res_pc.text
    # 手動切り替えスイッチが削除されていることを確認
    assert "PCモード表示中" not in html_pc
    assert "スマホ表示に切替" not in html_pc

    # 2. iPhone User-Agent でのアクセステスト (スマホアクセス時の自動認識)
    mobile_headers = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"}
    res_mobile = client.get("/", headers=mobile_headers)
    assert res_mobile.status_code == 200
    html_mobile = res_mobile.text
    assert "スマホ最適化モード表示中" not in html_mobile
    assert "Smartphone App-style Fixed Bottom Navigation Bar" in html_mobile, "Bottom navigation should exist"

    # 3. /events ページでの自動デバイス最適化テスト（モバイルアクセス時は絞り込み検索トグルが出現）
    res_events_mobile = client.get("/events", headers=mobile_headers)
    assert res_events_mobile.status_code == 200
    assert "絞り込み検索条件を表示/隠す" in res_events_mobile.text, "Mobile filter toggle should be present for mobile devices"

    print("[SUCCESS] All automatic device detection & mobile view tests passed successfully!")

if __name__ == "__main__":
    test_device_detection_logic()
