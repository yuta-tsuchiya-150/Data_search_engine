import os
import unittest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# 環境変数の設定
os.environ["STRIPE_PUBLISHABLE_KEY"] = "pk_test_sample"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_sample"
os.environ["STRIPE_PRICE_ID"] = "price_test_sample"
os.environ["FREE_REGISTRATION_CAMPAIGN"] = "false"

from app.main import app
from app.database import SessionLocal
from app.models.schema import User, TrialHistory

class TestStripeSubscriptionFlow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.db = SessionLocal()
        
        # テストデータのクリーンアップ
        self.test_email = "test_stripe_user@example.com"
        self.test_username = "stripe_test_user"
        
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

    def test_terms_and_privacy_pages(self):
        """利用規約とプライバシーポリシーの表示確認"""
        res = self.client.get("/terms")
        self.assertEqual(res.status_code, 200)
        self.assertIn("利用規約", res.text)
        self.assertIn("30日間の無料トライアル", res.text)
        self.assertIn("同一メールアドレス", res.text)

        res = self.client.get("/privacy")
        self.assertEqual(res.status_code, 200)
        self.assertIn("メールアドレス・個人情報の第三者提供・転売は一切行いません", res.text)
        self.assertIn("完全セーフガード", res.text)

    @patch("stripe.checkout.Session.create")
    def test_first_time_registration_gets_30_days_trial(self, mock_checkout_create):
        """初回登録時は30日間の無料トライアルが付与されること"""
        mock_checkout_create.return_value = MagicMock(url="https://checkout.stripe.com/pay/test_session_1")

        # 初回登録リクエスト
        res = self.client.post("/register", data={
            "username": self.test_username,
            "email": self.test_email,
            "password": "securepassword123"
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 303)
        self.assertEqual(res.headers["location"], "https://checkout.stripe.com/pay/test_session_1")

        # mockに渡された引数の検証
        mock_checkout_create.assert_called_once()
        call_kwargs = mock_checkout_create.call_args[1]
        
        # 初回なので trial_period_days == 30 が入っていること
        self.assertIn("subscription_data", call_kwargs)
        self.assertEqual(call_kwargs["subscription_data"]["trial_period_days"], 30)
        self.assertEqual(call_kwargs["metadata"]["is_first_time"], "true")
        self.assertEqual(call_kwargs["customer_email"], self.test_email)

    @patch("stripe.checkout.Session.create")
    def test_second_time_registration_no_trial_immediate_charge(self, mock_checkout_create):
        """同じメールアドレスの2回目登録時は無料トライアルなし（即時課金）となること"""
        mock_checkout_create.return_value = MagicMock(url="https://checkout.stripe.com/pay/test_session_2")

        # 過去に無料トライアルを利用した履歴を手動作成
        self.db.add(TrialHistory(email=self.test_email))
        self.db.commit()

        # 2回目の登録リクエスト
        res = self.client.post("/register", data={
            "username": self.test_username,
            "email": self.test_email,
            "password": "securepassword123"
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 303)
        self.assertEqual(res.headers["location"], "https://checkout.stripe.com/pay/test_session_2")

        mock_checkout_create.assert_called_once()
        call_kwargs = mock_checkout_create.call_args[1]

        # 2回目なので trial_period_days が存在しない（即時課金）こと
        self.assertNotIn("trial_period_days", call_kwargs.get("subscription_data", {}))
        self.assertEqual(call_kwargs["metadata"]["is_first_time"], "false")

    @patch("stripe.checkout.Session.retrieve")
    def test_payment_success_activates_user_and_records_trial_history(self, mock_retrieve):
        """決済成功時にユーザーが有効化され、TrialHistoryに記録されること"""
        # 事前に未払いユーザーを作成
        user = User(
            username=self.test_username,
            email=self.test_email,
            hashed_password="hash",
            is_paid=False,
            subscription_status="pending"
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        # Stripe Checkout Session モック
        mock_session = MagicMock()
        mock_session.customer = "cus_mock123"
        mock_session.subscription = "sub_mock123"
        mock_session.customer_email = self.test_email
        mock_session.metadata = {
            "user_id": str(user.id),
            "username": user.username,
            "email": user.email,
            "is_first_time": "true"
        }
        mock_retrieve.return_value = mock_session

        res = self.client.get(f"/payment/success?session_id=cs_test_mock")
        self.assertEqual(res.status_code, 200)
        self.assertIn("30日間無料トライアル開始", res.text)

        # DBの更新状態を検証（セッションキャッシュを更新）
        self.db.expire_all()
        updated_user = self.db.query(User).filter(User.id == user.id).first()
        self.assertTrue(updated_user.is_paid)
        self.assertEqual(updated_user.stripe_customer_id, "cus_mock123")
        self.assertEqual(updated_user.stripe_subscription_id, "sub_mock123")
        self.assertEqual(updated_user.subscription_status, "trialing")

        # TrialHistoryに記録されたことを検証
        history = self.db.query(TrialHistory).filter(TrialHistory.email == self.test_email).first()
        self.assertIsNotNone(history)

if __name__ == "__main__":
    unittest.main()
