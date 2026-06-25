"""
面试相关 SQLAlchemy ORM 模型
对应表: interview_weakness_reports, question_bank_items, question_bank_imports
"""

from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class WeaknessReportModel(Base):
    __tablename__ = "interview_weakness_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE"), unique=True
    )
    series_id: Mapped[str | None] = mapped_column(String, nullable=True)
    report_data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_weakness_report_user", "user_id", "created_at"),
        Index("idx_weakness_report_session", "session_id"),
    )


class QuestionBankItemModel(Base):
    __tablename__ = "question_bank_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String, default="manual")
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    origin_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    question_text: Mapped[str] = mapped_column(Text)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    difficulty: Mapped[str] = mapped_column(String, default="medium")
    target_skill: Mapped[str | None] = mapped_column(String, nullable=True)
    question_type: Mapped[str] = mapped_column(String, default="tech")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_question_bank_user", "user_id", "created_at"),
        Index("idx_question_bank_type", "question_type"),
        Index("idx_question_bank_difficulty", "difficulty"),
        Index("idx_question_bank_verified", "is_verified"),
    )


class QuestionBankImportModel(Base):
    __tablename__ = "question_bank_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    import_source: Mapped[str] = mapped_column(String, default="file")
    import_status: Mapped[str] = mapped_column(String, default="pending")
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_question_bank_imports_user", "user_id", "created_at"),
    )
