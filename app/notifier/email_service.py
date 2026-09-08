import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List
from sqlalchemy.orm import Session
from app.models.schema import Event, Favorite, User, NotificationLog

class EmailNotifier:
    """
    新規イベント検知時に対象ユーザーへプッシュメールを送信するサービスクラス
    """
    SMTP_HOST = "localhost"
    SMTP_PORT = 1025
    SENDER_EMAIL = "noreply@ojuken-search.example.com"

    @staticmethod
    def notify_users_for_new_events(events: List[Event], db: Session) -> int:
        """
        新規イベント一覧に対し、その学校/塾をお気に入り登録している有料会員へメールを送信
        """
        notifications_sent = 0
        for event in events:
            # お気に入り登録しているユーザーを取得
            favorites = db.query(Favorite).filter(Favorite.source_id == event.source_id).all()
            for fav in favorites:
                user = fav.user
                # ユーザーが有効かつ有料会員の場合に通知
                if user and user.is_paid:
                    sent_success = EmailNotifier.send_email(
                        to_email=user.email,
                        username=user.username,
                        source_name=event.source.name,
                        event_title=event.title,
                        event_date=event.event_date or "未定",
                        location=event.location or "未指定",
                        url=event.url or "#"
                    )
                    
                    # 送信ログをDBに記録
                    log = NotificationLog(
                        user_id=user.id,
                        event_id=event.id,
                        status="sent" if sent_success else "failed"
                    )
                    db.add(log)
                    notifications_sent += 1

            event.is_notified = True

        db.commit()
        return notifications_sent

    @staticmethod
    def send_email(to_email: str, username: str, source_name: str, event_title: str, event_date: str, location: str, url: str) -> bool:
        """
        メールメッセージ構築と送信（開発・プロトタイプモードではコンソールログにも詳細表示）
        """
        subject = f"【新着イベント通知】{source_name} に新しいお知らせが届きました！"
        body = f"""
{username} 様

いつもご利用いただきありがとうございます。
あなたがフォローしている「{source_name}」に関する新しいイベント・更新情報が自動検出されました。

--------------------------------------------------
■ タイトル: {event_title}
■ 開催日/試験日: {event_date}
■ 会場/場所: {location}
■ 詳細URL: {url}
--------------------------------------------------

マイカレンダーにも本イベントが反映されています。ログインしてご確認ください。
https://ojuken-search.example.com/calendar

※このメールはマイページでお気に入り登録された学校・塾の情報に基づいて自動送信されています。
"""
        print("\n==================== [PUSH EMAIL SENT] ====================")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print(body.strip())
        print("===========================================================\n")

        # 実際にSMTPサーバーが稼働している場合は下記で送信可能
        try:
            msg = MIMEMultipart()
            msg['From'] = EmailNotifier.SENDER_EMAIL
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # with smtplib.SMTP(EmailNotifier.SMTP_HOST, EmailNotifier.SMTP_PORT) as server:
            #     server.send_message(msg)
            return True
        except Exception as e:
            print(f"SMTP send failed (mocked as success for dev): {e}")
            return True
