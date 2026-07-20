"""
JD 匹配分析相关 SQLAlchemy ORM 模型
对应表: jd_analysis_results
"""

from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class JdAnalysisResultModel(Base):
    __tablename__ = "jd_analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    resume_source_type: Mapped[str] = mapped_column(String, default="manual_input")
    resume_source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resume_content_snapshot: Mapped[str] = mapped_column(Text)
    job_description: Mapped[str] = mapped_column(Text)
    analysis_result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_jd_analysis_user", "user_id", "created_at"),
    )
