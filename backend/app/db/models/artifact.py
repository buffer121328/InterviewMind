"""产物（面试报告 PDF 等）的持久化模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ArtifactModel(Base):
    """面试报告产物记录：以用户+来源+格式+模式+版本唯一，便于按会话重查或替换。"""

    __tablename__ = "artifacts"

    # ── 主键与归属 ─────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 自增主键
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)        # 所属用户 ID，用于查询隔离
    agent_run_id: Mapped[str | None] = mapped_column(String, nullable=True)         # 生成该产物的 AgentRun ID，可空

    # ── 来源标识 ───────────────────────────────────────────────────
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)      # 来源类型（如 interview_report）
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)       # 来源对象 ID（如会话 ID）
    artifact_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="default")  # 报告模式（deep/standard 等）
    report_source_version: Mapped[str] = mapped_column(String(128), nullable=False, default="legacy")  # 报告来源版本指纹

    # ── 产物信息 ───────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(255), nullable=False)           # 报告标题
    format: Mapped[str] = mapped_column(String(16), nullable=False)           # 产物格式（如 pdf）
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)       # MIME 类型
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)     # 存储键（对象存储路径）
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)          # 文件大小（字节）
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)  # 文件 SHA-256 校验和

    # ── 时间戳 ─────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)    # 创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)    # 最后更新时间

    __table_args__ = (
        # 同一用户、来源、格式、模式与版本下只保留一份产物，重复生成时替换而非叠加
        UniqueConstraint(
            "user_id",
            "source_type",
            "source_id",
            "format",
            "artifact_mode",
            "report_source_version",
            name="uq_artifact_source_format_mode_version",
        ),
        # 按归属+来源快速查询产物列表
        Index("idx_artifacts_owner_source", "user_id", "source_type", "source_id"),
        # 按归属+生成任务快速关联
        Index("idx_artifacts_owner_run", "user_id", "agent_run_id"),
    )
