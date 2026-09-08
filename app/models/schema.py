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
    is_paid = Column(Boolean, default=False)  # 有料会員フラグ
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("NotificationLog", back_populates="user", cascade="all, delete-orphan")

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(String, unique=True, index=True, nullable=False) # e.g. elementary_school
    name = Column(String, nullable=False)                                # e.g. 小学校お受験情報
    description = Column(Text, nullable=True)

    sources = relationship("Source", back_populates="category", cascade="all, delete-orphan")

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

    category = relationship("Category", back_populates="sources")
    events = relationship("Event", back_populates="source", cascade="all, delete-orphan")
    favorited_by = relationship("Favorite", back_populates="source", cascade="all, delete-orphan")

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    title = Column(String, index=True, nullable=False)
    content = Column(Text, nullable=True)
    url = Column(String, nullable=True)
    published_date = Column(String, nullable=True)                      # 発表日 / 更新日
    event_date = Column(String, index=True, nullable=True)               # イベント開催日・試験日 (YYYY-MM-DD)
    location = Column(String, nullable=True)                            # 開催場所・会場
    created_at = Column(DateTime, default=datetime.utcnow)
    is_notified = Column(Boolean, default=False)                         # メール通知済みフラグ

    source = relationship("Source", back_populates="events")
    notifications = relationship("NotificationLog", back_populates="event", cascade="all, delete-orphan")

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
