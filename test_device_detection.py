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
    assert "PCモード表示中" in html_pc, "PC mode indicator should be rendered"

    # 2. iPhone User-Agent でのアクセステスト (スマホ最適化モード)
    mobile_headers = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"}
    res_mobile = client.get("/", headers=mobile_headers)
    assert res_mobile.status_code == 200
    html_mobile = res_mobile.text
    assert "スマホ最適化モード表示中" in html_mobile, "Mobile mode indicator should be rendered"
    assert "Smartphone App-style Fixed Bottom Navigation Bar" in html_mobile, "Bottom navigation should exist"

    # 3. クエリパラメータ ?device=mobile / ?device=desktop による切り替えテスト
    res_query_mobile = client.get("/events?device=mobile", headers=pc_headers)
    assert res_query_mobile.status_code == 200
    assert "スマホ最適化モード表示中" in res_query_mobile.text, "Query parameter ?device=mobile should force mobile mode"
    assert "絞り込み検索条件を表示/隠す" in res_query_mobile.text, "Mobile filter toggle should be present"

    res_query_desktop = client.get("/events?device=desktop", headers=mobile_headers)
    assert res_query_desktop.status_code == 200
    assert "PCモード表示中" in res_query_desktop.text, "Query parameter ?device=desktop should force desktop mode"

    print("[SUCCESS] All device detection & mobile view tests passed successfully!")

if __name__ == "__main__":
    test_device_detection_logic()
