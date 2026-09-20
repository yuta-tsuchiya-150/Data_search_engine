import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.schema import Event, Favorite, User, NotificationLog

def _load_env_if_exists():
    """依存パッケージ不要で .env ファイルを確実にロード"""
    env_paths = [os.path.abspath(".env"), os.path.join(os.path.dirname(__file__), "..", "..", ".env")]
    for ep in env_paths:
        if os.path.exists(ep):
            try:
                with open(ep, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            clean_k = k.strip().lstrip('\ufeff')
                            clean_v = v.strip()
                            if clean_k not in os.environ or not os.environ[clean_k]:
                                os.environ[clean_k] = clean_v
                break
            except Exception:
                pass

_load_env_if_exists()

class EmailNotifier:
    """
    新規イベント検知時、新着回収ダイジェスト、AI自己修復時にプッシュメールを送信するサービスクラス
    """
    @staticmethod
    def get_smtp_config():
        _load_env_if_exists()
        return {
            "host": os.getenv("SMTP_HOST", "").strip(),
            "port": int(os.getenv("SMTP_PORT", "587")),
            "user": os.getenv("SMTP_USER", "").strip(),
            "password": os.getenv("SMTP_PASSWORD", "").strip(),
            "sender": os.getenv("SENDER_EMAIL", "noreply@ojuken-search.example.com").strip(),
            "admin_email": os.getenv("ADMIN_EMAIL", "user@example.com").strip()
        }


    @staticmethod
    def _send_raw_email(to_email: str, subject: str, body: str, header_label: str = "EMAIL NOTIFICATION") -> bool:
        """内部共通メール送信メソッド"""
        config = EmailNotifier.get_smtp_config()

        print(f"\n==================== [{header_label}] ====================")
        try:
            print(f"To: {to_email}")
            print(f"Subject: {subject}")
            print(body.strip())
        except UnicodeEncodeError:
            print(f"To: {to_email}")
            print(f"Subject: {subject.encode('utf-8', errors='replace').decode('utf-8', errors='replace')}")
            print(body.strip().encode('ascii', errors='replace').decode('ascii'))
        print("========================================================================\n")

        # SMTP設定がある場合は実送信
        if config["host"] and config["user"] and config["password"]:
            try:
                msg = MIMEMultipart()
                msg['From'] = config["sender"]
                msg['To'] = to_email
                msg['Subject'] = subject
                msg.attach(MIMEText(body, 'plain', 'utf-8'))

                if config["port"] == 465:
                    server = smtplib.SMTP_SSL(config["host"], config["port"], timeout=15)
                else:
                    server = smtplib.SMTP(config["host"], config["port"], timeout=15)
                    server.starttls()

                server.login(config["user"], config["password"])
                server.send_message(msg)
                server.quit()
                print(f"✅ Successfully sent email to {to_email}")
                return True
            except Exception as e:
                print(f"⚠️ SMTP send failed (logged safely): {e}")
                return False
        else:
            print(f"ℹ️ SMTP not fully configured (host={bool(config['host'])}, user={bool(config['user'])}, pass={bool(config['password'])}). Simulated in console.")
        return True

    @staticmethod
    def notify_admin_harvest_report(events: List[Event]) -> bool:
        """
        定期自動巡回で新着イベントが回収された際にマスターへダイジェストメールを送信
        """
        if not events:
            return False

        config = EmailNotifier.get_smtp_config()
        admin_email = config["admin_email"]

        subject = f"【DataSearchHub】新着イベントを {len(events)} 件回収しました！（自動巡回レポート）"
        
        # 学校ごとにイベントを整理
        grouped = {}
        for ev in events:
            s_name = ev.source.name if ev.source else "未分類"
            if s_name not in grouped:
                grouped[s_name] = []
            grouped[s_name].append(ev)

        lines = [
            "マスター、お疲れ様です。自動巡回エージェントです。",
            "",
            f"本日の定期巡回において、新着イベント情報を 【 {len(events)} 件 】 回収（自動登録）いたしました。",
            "回収されたイベント一覧は以下の通りです：",
            "",
            "=================================================="
        ]

        for s_name, ev_list in grouped.items():
            lines.append(f"■ 【{s_name}】 ({len(ev_list)}件)")
            for ev in ev_list:
                lines.append(f"  ・イベント: {ev.title}")
                if ev.event_date:
                    lines.append(f"    開催日/試験日: {ev.event_date}")
                if ev.location:
                    lines.append(f"    会場/場所: {ev.location}")
                if ev.url:
                    lines.append(f"    詳細URL: {ev.url}")
                lines.append("")

        lines.extend([
            "==================================================",
            "",
            "サイト内のマイカレンダーおよびイベント一覧にも即時反映されています。",
            "引き続き4時間おきに自動巡回・自律監視を継続いたします。"
        ])

        body = "\n".join(lines)
        return EmailNotifier._send_raw_email(to_email=admin_email, subject=subject, body=body, header_label="NEW HARVEST DIGEST REPORT")

    @staticmethod
    def send_test_email(to_email: str) -> bool:
        """
        管理画面からの接続テストメール送信
        """
        subject = "【DataSearchHub】メール送信テスト（接続確認成功）"
        body = f"""
マスター、こんにちは！

DataSearchHub のメール送信テストです。
このメールが届いていれば、メールサーバー（SMTP）の設定は完全に正常に稼働しています！

今後、定期巡回で新着イベントが回収された際や、AIがサイトの仕様変更を自己修復した際に、
このメールアドレス宛てに最新レポートが自動送信されます。

引き続きよろしくお願いいたします！
"""
        return EmailNotifier._send_raw_email(to_email=to_email, subject=subject, body=body, header_label="SMTP CONNECTION TEST EMAIL")

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
        return EmailNotifier._send_raw_email(to_email=admin_email, subject=subject, body=body, header_label="AI SELF-HEALING EMAIL REPORT")

    @staticmethod
    def notify_users_for_new_events(events: List[Event], db: Session) -> int:
        """
        新規イベント一覧に対し、その学校/塾をお気に入り登録している全会員ユーザーへメール通知を送信。
        ユーザーごとに新着イベントをまとめ、1通の読みやすいダイジェスト形式で送信します。
        """
        if not events:
            return 0

        from app.scraper.school_helper import extract_group_name

        # ユーザーごとに送信対象イベントをマッピング: user_id -> {"user": User, "events": List[Event]}
        user_events_map = {}

        # 全お気に入り設定を取得
        all_favorites = db.query(Favorite).all()

        for event in events:
            if not event.source:
                continue

            event_sid = event.source_id
            event_group = extract_group_name(event.source.name, event.source.url)

            for fav in all_favorites:
                user = fav.user
                # 会員登録ユーザー（有効なメールアドレス）を対象
                if not user or not user.email or "@" not in user.email:
                    continue
                # サンプル・ダミーアドレス（@example.com）は除外
                if "@example.com" in user.email:
                    continue

                fav_source = fav.source
                is_match = False
                if fav.source_id == event_sid:
                    is_match = True
                elif fav_source:
                    fav_group = extract_group_name(fav_source.name, fav_source.url)
                    if fav_group and fav_group == event_group:
                        is_match = True

                if is_match:
                    if user.id not in user_events_map:
                        user_events_map[user.id] = {
                            "user": user,
                            "events": []
                        }
                    # 重複追加防止
                    if event not in user_events_map[user.id]["events"]:
                        user_events_map[user.id]["events"].append(event)

        notifications_sent = 0

        # ユーザーごとにまとめて通知メール送信
        for uid, data in user_events_map.items():
            user = data["user"]
            user_events = data["events"]
            if not user_events:
                continue

            # 学校・塾グループごとにイベントを整理
            school_grouped = {}
            for ev in user_events:
                sname = extract_group_name(ev.source.name, ev.source.url) if ev.source else "お気に入り校"
                if sname not in school_grouped:
                    school_grouped[sname] = []
                school_grouped[sname].append(ev)

            # メールの件名作成
            school_names_list = list(school_grouped.keys())
            if len(school_names_list) == 1:
                subject = f"【新着イベント通知】{school_names_list[0]} に新しいスケジュールが追加されました！"
            elif len(school_names_list) == 2:
                subject = f"【新着イベント通知】{school_names_list[0]}・{school_names_list[1]} に新しいスケジュールが追加されました！"
            else:
                subject = f"【新着イベント通知】{school_names_list[0]} ほか計{len(school_names_list)}校に新しいスケジュールが追加されました！"

            # メールの本文作成
            lines = [
                f"{user.username} 様",
                "",
                "いつも DataSearchHub をご利用いただきありがとうございます。",
                "あなたがお気に入り登録（フォロー）している学校・塾にて、新しいイベント・説明会・入試日程が自動検出されました！",
                "",
                "=================================================="
            ]

            for s_name, ev_list in school_grouped.items():
                lines.append(f"■ 【{s_name}】 ({len(ev_list)}件の新着)")
                for ev in ev_list:
                    lines.append(f"  ・イベント名: {ev.title}")
                    lines.append(f"    開催日/試験日: {ev.event_date or '要確認・未定'}")
                    if ev.location and ev.location != "未指定":
                        lines.append(f"    会場/場所: {ev.location}")
                    if ev.official_url:
                        lines.append(f"    公式サイト/詳細: {ev.official_url}")
                    lines.append("")

            lines.extend([
                "==================================================",
                "",
                "あなたのマイカレンダーにも、上記スケジュールが自動的に同期・反映されています。",
                "ログインして詳細をご確認ください：",
                "http://2026091711175w334chu.conohawing.com/calendar",
                "",
                "※このメールはお気に入り登録中の学校・塾に新着予定が登録された際に自動配信されています。"
            ])

            body = "\n".join(lines)
            sent_success = EmailNotifier._send_raw_email(
                to_email=user.email,
                subject=subject,
                body=body,
                header_label="USER FAVORITE EVENT NOTIFICATION"
            )

            # 送信ログ記録
            for ev in user_events:
                if ev.id:
                    log = NotificationLog(
                        user_id=user.id,
                        event_id=ev.id,
                        status="sent" if sent_success else "failed"
                    )
                    db.add(log)

            notifications_sent += 1

        # 通知済みフラグをセット
        for event in events:
            event.is_notified = True

        try:
            db.commit()
        except Exception as commit_err:
            print(f"Error committing notification status: {commit_err}")
            db.rollback()

        return notifications_sent

    @staticmethod
    def send_email(to_email: str, username: str, source_name: str, event_title: str, event_date: str, location: str, url: str) -> bool:
        """
        ユーザー向け新着イベント単体プッシュメール（互換用）
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

マイカレンダーにも本イベントが反映されています。ログインしてご確認ください：
http://2026091711175w334chu.conohawing.com/calendar
"""
        return EmailNotifier._send_raw_email(to_email=to_email, subject=subject, body=body, header_label="USER PUSH EMAIL SENT")
