"""
投递追踪相关 SQLAlchemy ORM 模型
对应表: job_applications, application_events

扩展字段（BOSS 岗位自动化）：
- source_platform / source_url / external_job_id — 平台来源追踪
- captured_job_id — 关联采集岗位
- greeting_text — 使用的打招呼文案
- send_status / send_attempts / last_error / last_screenshot_path — 发送状态追踪
- jd_analysis_id / custom_resume_id — 关联分析资产
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

    # === BOSS 自动化扩展字段 ===
    source_platform: Mapped[str | None] = mapped_column(String, nullable=True)     # boss/lagou/...
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)          # 岗位链接
    external_job_id: Mapped[str | None] = mapped_column(String, nullable=True)     # 平台侧岗位ID
    captured_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)    # FK -> captured_jobs
    greeting_text: Mapped[str | None] = mapped_column(Text, nullable=True)          # 使用的打招呼文案
    send_status: Mapped[str | None] = mapped_column(String, nullable=True)          # pending/sent/failed/manual_takeover
    send_attempts: Mapped[int] = mapped_column(Integer, default=0)                 # 发送尝试次数
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)             # 最后错误信息
    last_screenshot_path: Mapped[str | None] = mapped_column(String, nullable=True) # 最后截图路径
    jd_analysis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)     # FK -> jd_analysis_results
    custom_resume_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 岗位专用简历 ID

    # 关系
    events: Mapped[list["ApplicationEventModel"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_job_applications_user", "user_id", "updated_at"),
        Index("idx_job_applications_status", "latest_status"),
        Index("idx_job_applications_send_status", "send_status"),
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
