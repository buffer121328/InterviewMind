"""提供产物相关后端功能。"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ArtifactModel(Base):
    """定义产物模型相关后端数据结构或服务组件。"""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="default")
    report_source_version: Mapped[str] = mapped_column(String(128), nullable=False, default="legacy")
    agent_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_type",
            "source_id",
            "format",
            "artifact_mode",
            "report_source_version",
            name="uq_artifact_source_format_mode_version",
        ),
        Index("idx_artifacts_owner_source", "user_id", "source_type", "source_id"),
        Index("idx_artifacts_owner_run", "user_id", "agent_run_id"),
    )
