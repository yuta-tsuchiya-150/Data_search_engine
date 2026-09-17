import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.schema import Event, Favorite, User, NotificationLog

class EmailNotifier:
    """
    新規イベント検知時およびAI自己修復時にプッシュメールを送信するサービスクラス
    """
    @staticmethod
    def get_smtp_config():
        return {
            "host": os.getenv("SMTP_HOST", "").strip(),
            "port": int(os.getenv("SMTP_PORT", "587")),
            "user": os.getenv("SMTP_USER", "").strip(),
            "password": os.getenv("SMTP_PASSWORD", "").strip(),
            "sender": os.getenv("SENDER_EMAIL", "noreply@ojuken-search.example.com").strip(),
            "admin_email": os.getenv("ADMIN_EMAIL", "user@example.com").strip()
        }

    @staticmethod
    def notify_users_for_new_events(events: List[Event], db: Session) -> int:
        """
        新規イベント一覧に対し、その学校/塾をお気に入り登録している有料会員へメールを送信
        """
        notifications_sent = 0
        for event in events:
            favorites = db.query(Favorite).filter(Favorite.source_id == event.source_id).all()
            for fav in favorites:
                user = fav.user
                if user and user.is_paid:
                    sent_success = EmailNotifier.send_email(
                        to_email=user.email,
                        username=user.username,
                        source_name=event.source.name if event.source else "学校・塾",
                        event_title=event.title,
                        event_date=event.event_date or "未定",
                        location=event.location or "未指定",
                        url=event.url or "#"
                    )
                    
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
    def send_self_healing_alert(healing_log) -> bool:
        """
        AI自律修復エージェントが自己治癒・救済処理を行った際にマスターへ通知メールを送信
        """
        config = EmailNotifier.get_smtp_config()
        admin_email = config["admin_email"]

        subject = f"【DataSearchHub AI通知】{healing_log.source_name} のスクレイピング設定を自己修復しました"
        body = f"""
マスター、お疲れ様です。AI自律修復エージェントです。

対象校「{healing_log.source_name}」のWebサイトにおいて仕様変更を検知し、
自己修復（Self-Healing）処理を実行いたしました。

--------------------------------------------------
■ 対象校・塾: {healing_log.source_name}
■ 対象URL: {healing_log.target_url}
■ 実行ステータス: {healing_log.status}
■ 検知理由: {healing_log.reason}
■ 救済/取得イベント件数: {healing_log.events_count} 件
■ 詳細サマリー:
{healing_log.details}
--------------------------------------------------

管理画面ダッシュボードでも過去のAI自己修復レポートをご確認いただけます。
引き続き24時間体制で自律巡回と自己治癒を継続いたします。
"""
        print("\n==================== [AI SELF-HEALING EMAIL REPORT] ====================")
        try:
            print(f"To: {admin_email}")
            print(f"Subject: {subject}")
            print(body.strip())
        except UnicodeEncodeError:
            print(f"To: {admin_email}")
            print(f"Subject: {subject.encode('utf-8', errors='replace').decode('utf-8', errors='replace')}")
            print(body.strip().encode('ascii', errors='replace').decode('ascii'))
        print("========================================================================\n")

        # SMTP設定がある場合は実送信
        if config["host"] and config["user"] and config["password"]:
            try:
                msg = MIMEMultipart()
                msg['From'] = config["sender"]
                msg['To'] = admin_email
                msg['Subject'] = subject
                msg.attach(MIMEText(body, 'plain', 'utf-8'))

                server = smtplib.SMTP(config["host"], config["port"], timeout=10)
                server.starttls()
                server.login(config["user"], config["password"])
                server.send_message(msg)
                server.quit()
                print(f"✅ Successfully sent self-healing email to {admin_email}")
                return True
            except Exception as e:
                print(f"⚠️ SMTP send failed (logged safely): {e}")
                return False
        return True

    @staticmethod
    def send_email(to_email: str, username: str, source_name: str, event_title: str, event_date: str, location: str, url: str) -> bool:
        """
        イベント新着プッシュメールの送信
        """
        config = EmailNotifier.get_smtp_config()
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
"""
        print("\n==================== [PUSH EMAIL SENT] ====================")
        try:
            print(f"To: {to_email}")
            print(f"Subject: {subject}")
            print(body.strip())
        except UnicodeEncodeError:
            print(f"To: {to_email}")
            print(f"Subject: {subject.encode('utf-8', errors='replace').decode('utf-8', errors='replace')}")
            print(body.strip().encode('ascii', errors='replace').decode('ascii'))
        print("===========================================================\n")

        if config["host"] and config["user"] and config["password"]:
            try:
                msg = MIMEMultipart()
                msg['From'] = config["sender"]
                msg['To'] = to_email
                msg['Subject'] = subject
                msg.attach(MIMEText(body, 'plain', 'utf-8'))

                server = smtplib.SMTP(config["host"], config["port"], timeout=10)
                server.starttls()
                server.login(config["user"], config["password"])
                server.send_message(msg)
                server.quit()
                return True
            except Exception as e:
                print(f"⚠️ SMTP send failed: {e}")
                return False
        return True
