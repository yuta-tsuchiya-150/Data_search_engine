from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_paid = Column(Boolean, default=True)  # デフォルトで全機能利用可能
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)             # True: 有効会員, False: 退会済み
    created_at = Column(DateTime, default=datetime.utcnow)
    withdrawn_at = Column(DateTime, nullable=True)        # 退会完了日時

    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("NotificationLog", back_populates="user", cascade="all, delete-orphan")
    keyword_alerts = relationship("KeywordAlert", back_populates="user", cascade="all, delete-orphan")
    source_requests = relationship("SourceRequest", back_populates="user", cascade="all, delete-orphan")
    personal_events = relationship("Event", back_populates="user", cascade="all, delete-orphan")

class KeywordAlert(Base):
    __tablename__ = "keyword_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    keyword = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="keyword_alerts")

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(String, unique=True, index=True, nullable=False) # e.g. elementary_school
    name = Column(String, nullable=False)                                # e.g. 小学校お受験情報
    description = Column(Text, nullable=True)

    sources = relationship("Source", back_populates="category", cascade="all, delete-orphan")

OFFICIAL_SITE_MAP = {
    "keio_yochisha": "https://www.yochisha.keio.ac.jp/",
    "gyosei_primary": "https://www.gyosei-e.ed.jp/",
    "rikkyo_primary": "https://prim.rikkyo.ac.jp/",
    "waseda_jitsugyo": "https://www.wasedajg.ed.jp/elementary/",
    "keio_yokohama": "https://www.yokohama-e.keio.ac.jp/",
    "aoyama_gakuin": "https://www.age.aoyama.ed.jp/",
    "gakushuin_primary": "https://www.gakushuin.ac.jp/prim/",
    "shirayuri_primary": "https://shirayuri-e.ed.jp/",
    "seishin_primary": "https://www.tky-sacred-heart.ed.jp/",
    "toyoeiwa_primary": "https://ps.toyoeiwa.ac.jp/",
    "rikkyojogakuin": "https://es.rikkyojogakuin.ac.jp/",
    "denenchofu_futaba": "https://www.denenchofufutaba.ed.jp/elementary/",
    "koen_primary": "https://www.koen-ejh.ed.jp/",
    "showa_primary": "https://es.swu.ac.jp/",
    "seijo_primary": "https://www.seijogakuen.ed.jp/shoto/",
    "seikei_primary": "https://www.seikei.ac.jp/elementary/",
    "toho_primary": "https://www.toho.ed.jp/",
    "tohogakuen_primary": "https://shogakko.toho.ac.jp/",
    "meisei_primary": "https://www.meisei.ac.jp/es/",
    "kunion_primary": "https://www.onsho.ed.jp/",
    "tcu_primary": "https://www.tcu-elementary.ed.jp/",
    "dominic_primary": "https://www.dominic.ed.jp/",
    "wako_primary": "https://www.wako.ed.jp/e/",
    "takehaya_es": "https://www2.u-gakugei.ac.jp/~takesyo/",
    "oizumi_es": "https://www.es.oizumi.u-gakugei.ac.jp/",
    "setagaya_es": "https://www.setagaya-es.u-gakugei.ac.jp/",
    "koganei_es": "https://www2.u-gakugei.ac.jp/~kanesyo/",
    "ocha_es": "https://www.fz.ocha.ac.jp/fs/",
    "tsukuba_es": "https://www.elementary-s.tsukuba.ac.jp/",
    "yokohama_eiwa": "https://www.yokohama-eiwa.ac.jp/shougakkou/",
    "caritas_primary": "https://www.caritas.ed.jp/",
    "senzoku_primary": "https://www.senzoku.ed.jp/",
    "kamakura_women": "https://www.kamakura-u.ac.jp/elementary/",
    "sagami_women": "https://www.sagami-wu.ac.jp/sho/",
    "kanto_primary": "https://es.kanto-gakuin.ac.jp/",
    "kanto_mutsuura": "https://kgm-es.jp/",
    "cecilia_primary": "https://www.st-cecilia-e.ed.jp/",
    "seika_primary": "https://www.seika.ed.jp/",
    "rieikai": "https://www.rieikai.com/",
    "kogumasakai": "https://www.kogumakai.co.jp/",
    "jac_infant": "https://www.jac-youjikyouiku.com/",
    "shingakai": "https://www.shingakai.co.jp/",
    "慶應": "https://www.yochisha.keio.ac.jp/",
    "暁星": "https://www.gyosei-e.ed.jp/",
    "立教": "https://prim.rikkyo.ac.jp/",
    "早稲田": "https://www.wasedajg.ed.jp/elementary/",
    "青山": "https://www.age.aoyama.ed.jp/",
    "学習院": "https://www.gakushuin.ac.jp/prim/",
    "白百合": "https://shirayuri-e.ed.jp/",
    "聖心": "https://www.tky-sacred-heart.ed.jp/",
    "東洋英和": "https://ps.toyoeiwa.ac.jp/",
    "雙葉": "https://www.denenchofufutaba.ed.jp/elementary/",
    "成蹊": "https://www.seikei.ac.jp/elementary/",
    "成城": "https://www.seijogakuen.ed.jp/shoto/",
    "洗足": "https://www.senzoku.ed.jp/",
    "精華": "https://www.seika.ed.jp/",
    "理英会": "https://www.rieikai.com/",
    "こぐま": "https://www.kogumakai.co.jp/",
    "ジャック": "https://www.jac-youjikyouiku.com/",
    "伸芽会": "https://www.shingakai.co.jp/"
}

SPECIFIC_EVENT_URL_MAP = {
    "秋のキャンパス見学会": "https://prim.rikkyo.ac.jp/entrance/openschool/guidance2026.html",
    "立教小学校": "https://prim.rikkyo.ac.jp/entrance/openschool/guidance2026.html",
}

def resolve_official_url(target_url: str, source_obj=None, title: str = "") -> str:
    # 0. タイトル・キーワードの特定イベントディープリンク判定
    if title and "キャンパス見学" in title and ("立教" in title or (source_obj and "立教" in getattr(source_obj, "name", ""))):
        return "https://prim.rikkyo.ac.jp/entrance/openschool/guidance2026.html"

    for key, deep_url in SPECIFIC_EVENT_URL_MAP.items():
        if key in title:
            return deep_url

    # 1. 外部の実在URL（特定ページかつ127.0.0.1/localhost/example.comでないもの）であれば優先
    if target_url and target_url.startswith(("http://", "https://")) and not ("127.0.0.1" in target_url or "localhost" in target_url or "example.com" in target_url):
        return target_url

    # 2. Source オブジェクトからのキーワード判定
    if source_obj:
        sid = getattr(source_obj, "source_id", "") or ""
        for key, official_url in OFFICIAL_SITE_MAP.items():
            if key in sid:
                return official_url

        sname = getattr(source_obj, "name", "") or ""
        for key, official_url in OFFICIAL_SITE_MAP.items():
            if key in sname:
                return official_url

        surl = getattr(source_obj, "url", "") or ""
        if surl and surl.startswith(("http://", "https://")) and not ("127.0.0.1" in surl or "localhost" in surl or "example.com" in surl):
            return surl

    # 3. target_url 内のキーワード判定
    if target_url:
        for key, official_url in OFFICIAL_SITE_MAP.items():
            if key in target_url:
                return official_url

    # 4. エラー回避フォールバック
    from urllib.parse import quote
    query_name = getattr(source_obj, "name", "小学校お受験") if source_obj else "小学校お受験"
    search_query = quote(f"{query_name} {title} 公式サイト".strip())
    return f"https://www.google.com/search?q={search_query}"

class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(String, unique=True, index=True, nullable=False) # e.g. keio_yochisha
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    name = Column(String, nullable=False)                                # e.g. 慶應義塾幼稚舎
    type = Column(String, nullable=False)                                # e.g. school, cram_school
    url = Column(String, nullable=False)
    schedule_interval_minutes = Column(Integer, default=60)
    selectors_json = Column(Text, nullable=False)                        # スクレイピングルール (JSON文字列)
    last_scraped_at = Column(DateTime, nullable=True)                    # 最終巡回実行日時

    category = relationship("Category", back_populates="sources")
    events = relationship("Event", back_populates="source", cascade="all, delete-orphan")
    favorited_by = relationship("Favorite", back_populates="source", cascade="all, delete-orphan")

    @property
    def official_url(self) -> str:
        return resolve_official_url(self.url, self)

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)     # 個人専用カスタム予定の場合に設定
    title = Column(String, index=True, nullable=False)
    content = Column(Text, nullable=True)
    url = Column(String, nullable=True)
    published_date = Column(String, nullable=True)                      # 発表日 / 更新日
    event_date = Column(String, index=True, nullable=True)               # イベント開催日・試験日 (YYYY-MM-DD)
    location = Column(String, nullable=True)                            # 開催場所・会場
    created_at = Column(DateTime, default=datetime.utcnow)
    is_notified = Column(Boolean, default=False)                         # メール通知済みフラグ

    source = relationship("Source", back_populates="events")
    user = relationship("User", back_populates="personal_events")
    notifications = relationship("NotificationLog", back_populates="event", cascade="all, delete-orphan")

    @property
    def official_url(self) -> str:
        return resolve_official_url(self.url, self.source, title=self.title)

class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="favorites")
    source = relationship("Source", back_populates="favorited_by")

class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="sent")                              # sent, failed

    user = relationship("User", back_populates="notifications")
    event = relationship("Event", back_populates="notifications")

class SourceRequest(Base):
    __tablename__ = "source_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    url = Column(String, nullable=False)
    note = Column(String, nullable=True)                                 # リクエストメモ・学校名など
    status = Column(String, default="pending")                           # pending, approved, rejected
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="source_requests")

class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)                                # e.g. YouTube: 立教小学校面接合格ガイド
    type = Column(String, nullable=False, default="document")             # youtube, document, guide
    source_url = Column(String, nullable=True)                           # YouTube URLや関連資料URL
    content = Column(Text, nullable=False)                                # ドキュメント本文・文字起こしデータ
    created_at = Column(DateTime, default=datetime.utcnow)

class AISelfHealingLog(Base):
    __tablename__ = "ai_self_healing_logs"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    source_name = Column(String, nullable=False)
    target_url = Column(String, nullable=True)
    status = Column(String, default="repaired")                          # repaired, ai_extracted, failed, no_change
    reason = Column(String, nullable=True)                               # e.g. ゼロ件検知 (0 items matched)
    old_selectors = Column(Text, nullable=True)                         # 変更前セレクタJSON
    new_selectors = Column(Text, nullable=True)                         # 変更後セレクタJSON
    events_count = Column(Integer, default=0)                           # 救済/取得できたイベント件数
    details = Column(Text, nullable=True)                                # AIによる分析詳細
    created_at = Column(DateTime, default=datetime.utcnow)

    source = relationship("Source", backref="self_healing_logs")

