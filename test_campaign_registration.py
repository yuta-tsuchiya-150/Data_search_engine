import os
import unittest
from fastapi.testclient import TestClient

# キャンペーンモードを有効化
os.environ["FREE_REGISTRATION_CAMPAIGN"] = "true"
os.environ["STRIPE_PUBLISHABLE_KEY"] = "pk_live_sample"
os.environ["STRIPE_SECRET_KEY"] = "sk_live_sample"
os.environ["STRIPE_PRICE_ID"] = "price_sample"

from app.main import app
from app.database import SessionLocal
from app.models.schema import User, TrialHistory

class TestCampaignRegistrationFlow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.db = SessionLocal()
        self.test_email = "campaign_unit_test@example.com"
        self.test_username = "campaign_unit_user"

        self.db.query(User).filter(
            (User.email == self.test_email) | (User.username == self.test_username)
        ).delete()
        self.db.query(TrialHistory).filter(TrialHistory.email == self.test_email).delete()
        self.db.commit()

    def tearDown(self):
        self.db.query(User).filter(
            (User.email == self.test_email) | (User.username == self.test_username)
        ).delete()
        self.db.query(TrialHistory).filter(TrialHistory.email == self.test_email).delete()
        self.db.commit()
        self.db.close()

    def test_campaign_registration_creates_paid_user_without_stripe_redirect(self):
        """キャンペーン期間中はカード決済画面に飛ばず直接ダッシュボードへ遷移し、即座に有料会員となること"""
        res = self.client.post("/register", data={
            "username": self.test_username,
            "email": self.test_email,
            "password": "securepassword123"
        }, follow_redirects=False)

        # 303 Redirect to dashboard with campaign_welcome param
        self.assertEqual(res.status_code, 303)
        self.assertEqual(res.headers["location"], "/dashboard?campaign_welcome=1")
        self.assertIn("current_user", res.headers.get("set-cookie", ""))

        # DB検証
        user = self.db.query(User).filter(User.username == self.test_username).first()
        self.assertIsNotNone(user)
        self.assertTrue(user.is_paid)
        self.assertEqual(user.subscription_status, "campaign_free")

    def test_campaign_page_wording(self):
        """登録画面にキャンペーン案内文言が表示されていること"""
        res = self.client.get("/register")
        self.assertEqual(res.status_code, 200)
        self.assertIn("期間限定 無料キャンペーン実施中！", res.text)
        self.assertIn("カード登録不要", res.text)
        self.assertIn("有料化のタイミングは現在<strong>未定</strong>です", res.text)
        self.assertIn("事前にご登録メールアドレス宛にお伝え", res.text)

if __name__ == "__main__":
    unittest.main()
