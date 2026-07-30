"""Agent 评测中心的版本化数据集、运行、分数、标注、校准与门禁模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EvaluationSuiteModel(Base):
    """用户拥有的评测套件，关联 Agent、数据集和门禁策略。"""

    __tablename__ = "evaluation_suites"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_dataset_versions.id", ondelete="RESTRICT"), nullable=False
    )
    rubric_version: Mapped[str] = mapped_column(String(160), nullable=False)
    gate_policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_gate_policies.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_evaluation_suite_owner_name"),
    )


class EvaluationDatasetVersionModel(Base):
    """不可变版本化评测数据集；locked 后只能创建新版本或 retired。"""

    __tablename__ = "evaluation_dataset_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="local")
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "name", "version", name="uq_evaluation_dataset_owner_version"
        ),
        Index("idx_evaluation_dataset_owner_status", "user_id", "status"),
    )


class EvaluationCaseModel(Base):
    """数据集案例；输入和 Ground Truth 使用 Fernet 密文保存。"""

    __tablename__ = "evaluation_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    case_key: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    input_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expected_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "case_key", name="uq_evaluation_case_dataset_key"
        ),
        Index("idx_evaluation_case_dataset_category", "dataset_version_id", "category"),
    )


class EvaluationRunModel(Base):
    """评测业务聚合，AgentRun 只负责队列和可恢复生命周期。"""

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    suite_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_suites.id", ondelete="RESTRICT"), nullable=False
    )
    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(String(160), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_config_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    baseline_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="SET NULL"), nullable=True
    )
    repetition_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    include_judges: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    budget: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_evaluation_run_owner_created", "user_id", "created_at"),
        Index("idx_evaluation_run_owner_status", "user_id", "status"),
    )


class EvaluationCaseRunModel(Base):
    """单案例真实 Agent 输出、Trace 引用和汇总评分。"""

    __tablename__ = "evaluation_case_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    evaluation_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_cases.id", ondelete="RESTRICT"), nullable=False
    )
    repetition_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actual_output_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    record_sanitized: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    hard_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id",
            "case_id",
            "repetition_index",
            name="uq_evaluation_case_run_repetition",
        ),
        Index("idx_evaluation_case_run_status", "evaluation_run_id", "status"),
    )


class EvaluationScoreModel(Base):
    """来源分离的自动、人工或用户反馈分数。"""

    __tablename__ = "evaluation_scores"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_case_runs.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info")
    hard_gate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metric_version: Mapped[str] = mapped_column(String(80), nullable=False, default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "case_run_id",
            "metric_name",
            "source",
            "metric_version",
            name="uq_evaluation_score_metric_version",
        ),
    )


class EvaluationAnnotationModel(Base):
    """append-only 人工标注 revision 和专家裁决。"""

    __tablename__ = "evaluation_annotations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_case_runs.id", ondelete="CASCADE"), nullable=False
    )
    annotator_user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reviewer_key: Mapped[str] = mapped_column(String(120), nullable=False)
    blind: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rubric_version: Mapped[str] = mapped_column(String(160), nullable=False)
    annotation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    labels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence_spans: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    comment_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    adjudication: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "case_run_id", "revision", name="uq_evaluation_annotation_revision"
        ),
        Index("idx_evaluation_annotation_case_metric", "case_run_id", "metric_name"),
    )


class EvaluationCalibrationModel(Base):
    """不可变 Judge Calibration Version 及一致性指标。"""

    __tablename__ = "evaluation_calibrations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)
    judge_version: Mapped[str] = mapped_column(String(160), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(160), nullable=False)
    human_sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    statistics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EvaluationGatePolicyModel(Base):
    """版本化发布门禁策略，生产激活不覆盖历史版本。"""

    __tablename__ = "evaluation_gate_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    hard_gates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metric_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    regression_tolerances: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    minimum_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "name", "version", name="uq_evaluation_gate_owner_version"
        ),
    )


class EvaluationGateResultModel(Base):
    """一次不可变门禁检查结果，供 Prompt 发布审计和回放。"""

    __tablename__ = "evaluation_gate_results"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    evaluation_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    gate_policy_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_gate_policies.id", ondelete="RESTRICT"), nullable=False
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blocked_by: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
