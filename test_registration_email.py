import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.notifier.email_service import EmailNotifier

def test_registration_notification():
    # 1. EmailNotifier 単体メソッドのテスト
    result = EmailNotifier.notify_admin_new_user_registered(
        username="test_parent_user",
        email="parent_sample@example.com"
    )
    assert result is True, "Notification method should execute successfully"

    # 2. /register エンドポイント経由の結合テスト
    client = TestClient(app)
    unique_user = f"user_{uuid.uuid4().hex[:8]}"
    unique_email = f"{unique_user}@test.com"

    res = client.post(
        "/register",
        data={
            "username": unique_user,
            "email": unique_email,
            "password": "Password123!"
        },
        follow_redirects=False
    )
    assert res.status_code == 303, f"Expected 303 redirect, got {res.status_code}"
    assert res.headers["location"] == "/dashboard"

    print("[SUCCESS] New user registration email notification test passed successfully!")

if __name__ == "__main__":
    test_registration_notification()
