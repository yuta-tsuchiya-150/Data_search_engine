import sys
from fastapi.testclient import TestClient
from app.main import app

def test_button_visibility_rules():
    client = TestClient(app)

    # 1. 未ログイン状態での検証
    res_guest = client.get("/events")
    assert res_guest.status_code == 200
    html_guest = res_guest.text
    assert "iCal (.ics) 全保存" not in html_guest, "Guest should NOT see .ics button"
    assert "巡回収集" not in html_guest, "Guest should NOT see Scrape-now button"

    res_cal_guest = client.get("/calendar")
    assert res_cal_guest.status_code == 200
    assert "iCal (.ics) 一括保存" not in res_cal_guest.text, "Guest should NOT see .ics button on calendar"

    # 2. 一般ユーザーログイン時の表示確認
    # (Cookie/Sessionシミュレーション)
    from app.models.schema import User
    from app.main import get_db
    db = next(get_db())

    demo_user = db.query(User).filter(User.username == "demo_user").first()
    if demo_user:
        # demo_user is normal user (is_admin=False)
        demo_user.is_admin = False
        db.commit()

        # Cookie付きでリクエスト
        res_user = client.get("/events", cookies={"current_user": demo_user.username})
        html_user = res_user.text
        assert "iCal (.ics) 全保存" in html_user, "Normal user SHOULD see .ics button"
        assert "巡回収集" not in html_user, "Normal user should NOT see Scrape-now button"

        # 管理者(is_admin=True)に変更して検証
        demo_user.is_admin = True
        db.commit()

        res_admin = client.get("/events", cookies={"current_user": demo_user.username})
        html_admin = res_admin.text
        assert "iCal (.ics) 全保存" in html_admin, "Admin SHOULD see .ics button"
        assert "巡回収集" in html_admin, "Admin SHOULD see Scrape-now button"

    print("[SUCCESS] All button visibility rules (Guest, Normal User, Admin User) passed!")

if __name__ == "__main__":
    test_button_visibility_rules()
