"""用户满意度反馈模型:面试/简历优化任务完成后的可空星级、方面多选与说明。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UserFeedbackModel(Base):
    """用户对单个任务实例的满意度反馈,按 owner + 任务实例幂等。"""

    __tablename__ = "user_feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_key: Mapped[str] = mapped_column(String(256), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    satisfied_aspects: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    dissatisfied_aspects: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_required")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewer_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_dataset_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "agent_type", "ref_key", name="uq_user_feedback_owner_ref"
        ),
        Index("idx_user_feedback_owner_agent_created", "user_id", "agent_type", "created_at"),
        Index("idx_user_feedback_owner_review", "user_id", "review_status", "created_at"),
    )
