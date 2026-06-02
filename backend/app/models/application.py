"""
投递追踪相关 SQLAlchemy ORM 模型
对应表: job_applications, application_events
"""

from datetime import datetime
from sqlalchemy import String, Text, Integer, ForeignKey, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class JobApplicationModel(Base):
    __tablename__ = "job_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String)
    company_name: Mapped[str] = mapped_column(String)
    job_title: Mapped[str] = mapped_column(String)
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_resume_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_status: Mapped[str] = mapped_column(String, default="saved")
    priority: Mapped[str] = mapped_column(String, default="medium")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    # 关系
    events: Mapped[list["ApplicationEventModel"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_job_applications_user", "user_id", "updated_at"),
        Index("idx_job_applications_status", "latest_status"),
    )


class ApplicationEventModel(Base):
    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_applications.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String)
    event_time: Mapped[datetime] = mapped_column(DateTime)
    event_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    application: Mapped["JobApplicationModel"] = relationship(back_populates="events")

    __table_args__ = (
        Index("idx_application_events_app", "application_id", "event_time"),
    )
