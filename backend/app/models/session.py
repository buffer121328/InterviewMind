"""
会话相关 SQLAlchemy ORM 模型
对应表: sessions, messages, user_profile
"""

from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class SessionModel(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default_user")
    title: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    mode: Mapped[str] = mapped_column(String)
    resume_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    interview_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    max_questions: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String, default="active")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    candidate_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    series_id: Mapped[str | None] = mapped_column(String, nullable=True)
    round_index: Mapped[int] = mapped_column(Integer, default=1)
    round_type: Mapped[str] = mapped_column(String, default="tech_initial")
    parent_session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.session_id"), nullable=True
    )

    # 关系
    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_session_updated", "updated_at"),
        Index("idx_session_status", "status"),
        Index("idx_session_mode", "mode"),
        Index("idx_session_user", "user_id"),
        Index("idx_session_user_pinned", "user_id", "pinned", "updated_at"),
        Index("idx_session_series", "series_id"),
        Index("idx_session_parent", "parent_session_id"),
    )


class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    question_index: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    audio_url: Mapped[str | None] = mapped_column(String, nullable=True)

    session: Mapped["SessionModel"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("idx_message_session", "session_id", "timestamp"),
        Index("idx_message_timestamp", "timestamp"),
    )


class UserProfileModel(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, unique=True)
    profile_data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
