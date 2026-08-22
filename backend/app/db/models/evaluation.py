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

    id: Mapped[str] = mapped_column(String, primary_key=True)                  # 套件主键（UUID）
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)   # 所属用户 ID
    name: Mapped[str] = mapped_column(String(160), nullable=False)             # 套件名称
    agent_name: Mapped[str] = mapped_column(String(160), nullable=False)       # 被评测的 Agent 名称
    description: Mapped[str | None] = mapped_column(Text, nullable=True)       # 套件说明
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_dataset_versions.id", ondelete="RESTRICT"), nullable=False
    )  # 引用数据集版本；被引用时禁止删除
    rubric_version: Mapped[str] = mapped_column(String(160), nullable=False)   # 评分规范版本
    gate_policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_gate_policies.id", ondelete="SET NULL"), nullable=True
    )  # 引用门禁策略；删除后置空
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)     # 创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)     # 最后更新时间

    __table_args__ = (
        # 同一用户下套件名称唯一
        UniqueConstraint("user_id", "name", name="uq_evaluation_suite_owner_name"),
    )


class EvaluationDatasetVersionModel(Base):
    """不可变版本化评测数据集；locked 后只能创建新版本或 retired。"""

    __tablename__ = "evaluation_dataset_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)                # 数据集版本主键（UUID）
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)  # 所属用户 ID
    name: Mapped[str] = mapped_column(String(160), nullable=False)           # 数据集名称
    version: Mapped[str] = mapped_column(String(80), nullable=False)         # 版本号
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # 状态：draft/locked/retired
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 案例数量
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="local")  # 数据来源（local/import 等）
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)   # 内容指纹，用于防篡改校验
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)   # 创建时间
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 锁定时间；锁定后不可变更

    __table_args__ = (
        # 同一用户下“名称+版本”唯一
        UniqueConstraint(
            "user_id", "name", "version", name="uq_evaluation_dataset_owner_version"
        ),
        # 按用户+状态查询数据集列表
        Index("idx_evaluation_dataset_owner_status", "user_id", "status"),
    )


class EvaluationCaseModel(Base):
    """数据集案例；输入和 Ground Truth 使用 Fernet 密文保存。"""

    __tablename__ = "evaluation_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True)               # 案例主键（UUID）
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_dataset_versions.id", ondelete="CASCADE"), nullable=False
    )  # 所属数据集版本；随版本删除级联删除
    case_key: Mapped[str] = mapped_column(String(160), nullable=False)      # 案例键（版本内唯一）
    category: Mapped[str] = mapped_column(String(120), nullable=False)      # 案例分类
    input_encrypted: Mapped[str] = mapped_column(Text, nullable=False)      # 输入（Fernet 密文）
    expected_encrypted: Mapped[str] = mapped_column(Text, nullable=False)   # Ground Truth（Fernet 密文）
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 标签列表
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")  # 严重程度
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)  # 内容指纹
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # 创建时间

    __table_args__ = (
        # 同一数据集版本内案例键唯一
        UniqueConstraint(
            "dataset_version_id", "case_key", name="uq_evaluation_case_dataset_key"
        ),
        # 按版本+分类查询案例
        Index("idx_evaluation_case_dataset_category", "dataset_version_id", "category"),
    )


class EvaluationRunModel(Base):
    """评测业务聚合，AgentRun 只负责队列和可恢复生命周期。"""

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)                 # 评测运行主键（UUID）
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)  # 所属用户 ID
    suite_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_suites.id", ondelete="RESTRICT"), nullable=False
    )  # 引用的评测套件；被引用时禁止删除
    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )  # 关联的 AgentRun；删除后置空
    smoke_batch_id: Mapped[str | None] = mapped_column(String(160), nullable=True)  # 全 Agent 冒烟批次；单 Agent 或高级运行为空
    agent_name: Mapped[str] = mapped_column(String(160), nullable=False)      # 被评测 Agent 名称
    agent_version: Mapped[str] = mapped_column(String(160), nullable=False)   # 被评测 Agent 版本
    prompt_name: Mapped[str | None] = mapped_column(String(160), nullable=True)  # 关联提示词名称
    prompt_version: Mapped[str | None] = mapped_column(String(160), nullable=True)  # 关联提示词版本
    model_config_hash: Mapped[str] = mapped_column(String(256), nullable=False)  # 模型配置指纹
    dataset_version: Mapped[str] = mapped_column(String(160), nullable=False)  # 数据集版本号
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")  # 运行状态：queued/running/…
    baseline_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="SET NULL"), nullable=True
    )  # 基准运行（用于回归对比）；删除后置空
    repetition_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 每个案例重复执行次数
    include_judges: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 是否启用 Judge 模型
    budget: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # 成本/次数预算
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # 聚合结果摘要
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 开始时间
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 结束时间
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)    # 创建时间

    __table_args__ = (
        # 按用户+创建时间查询运行历史
        Index("idx_evaluation_run_owner_created", "user_id", "created_at"),
        # 按用户+状态查询运行列表
        Index("idx_evaluation_run_owner_status", "user_id", "status"),
        # 按 owner+批次查询一键全 Agent 冒烟的同批运行
        Index("idx_evaluation_run_owner_smoke_batch", "user_id", "smoke_batch_id"),
    )


class EvaluationCaseRunModel(Base):
    """单案例真实 Agent 输出、Trace 引用和汇总评分。"""

    __tablename__ = "evaluation_case_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)                # 案例运行主键（UUID）
    evaluation_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )  # 所属评测运行；随运行删除级联删除
    case_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_cases.id", ondelete="RESTRICT"), nullable=False
    )  # 执行的案例；被引用时禁止删除
    repetition_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 重复执行序号
    status: Mapped[str] = mapped_column(String(32), nullable=False)          # 案例运行状态
    actual_output_encrypted: Mapped[str] = mapped_column(Text, nullable=False)  # Agent 实际输出（Fernet 密文）
    record_sanitized: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # 脱敏后的执行记录
    trace_id: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 关联 Trace ID
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 耗时（毫秒）
    token_usage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # token 用量
    hard_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 硬门禁是否通过
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 汇总评分
    error_category: Mapped[str | None] = mapped_column(String(160), nullable=True)  # 错误分类
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 是否需要人工复核
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_required")  # 复核状态
    review_resolver_key: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 复核解决键
    review_resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 复核解决时间
    review_resolution_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)  # 复核解决说明
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)   # 创建时间
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 完成时间

    __table_args__ = (
        # 同一运行内“案例+重复序号”唯一
        UniqueConstraint(
            "evaluation_run_id",
            "case_id",
            "repetition_index",
            name="uq_evaluation_case_run_repetition",
        ),
        # 按运行+状态查询案例运行
        Index("idx_evaluation_case_run_status", "evaluation_run_id", "status"),
    )


class EvaluationScoreModel(Base):
    """来源分离的自动、人工或用户反馈分数。"""

    __tablename__ = "evaluation_scores"

    id: Mapped[str] = mapped_column(String, primary_key=True)                  # 分数主键（UUID）
    case_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_case_runs.id", ondelete="CASCADE"), nullable=False
    )  # 所属案例运行；随案例运行删除级联删除
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)      # 指标名称
    value: Mapped[float | None] = mapped_column(Float, nullable=True)          # 指标分值；缺分数时为空
    status: Mapped[str] = mapped_column(String(32), nullable=False)            # 指标状态（passed/failed 等）
    source: Mapped[str] = mapped_column(String(32), nullable=False)            # 来源：auto/human/user_feedback
    reason_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)  # 脱敏后的评分理由
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info")  # 严重程度
    hard_gate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 是否属于硬门禁指标
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 证据引用列表
    metric_version: Mapped[str] = mapped_column(String(80), nullable=False, default="1")  # 指标版本
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)     # 创建时间

    __table_args__ = (
        # 同一案例运行内“指标+来源+版本”唯一
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

    id: Mapped[str] = mapped_column(String, primary_key=True)                 # 标注主键（UUID）
    case_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_case_runs.id", ondelete="CASCADE"), nullable=False
    )  # 所属案例运行；随案例运行删除级联删除
    annotator_user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)  # 标注人用户 ID
    reviewer_key: Mapped[str] = mapped_column(String(120), nullable=False)     # 复核键（关联复核者）
    blind: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # 是否盲标（不泄露来源）
    rubric_version: Mapped[str] = mapped_column(String(160), nullable=False)   # 评分规范版本
    annotation_type: Mapped[str] = mapped_column(String(32), nullable=False)   # 标注类型（score/comment 等）
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)      # 被标注指标
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)                 # 标注内容
    labels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 标签列表
    evidence_spans: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 证据片段引用
    comment_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)  # 脱敏后的标注评论
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)     # 标注置信度
    revision: Mapped[int] = mapped_column(Integer, nullable=False)             # 标注修订号（append-only 递增）
    adjudication: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 是否为专家裁决
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)     # 创建时间

    __table_args__ = (
        # 同一案例运行内修订号唯一，保证 append-only
        UniqueConstraint(
            "case_run_id", "revision", name="uq_evaluation_annotation_revision"
        ),
        # 按案例+指标查询标注
        Index("idx_evaluation_annotation_case_metric", "case_run_id", "metric_name"),
    )


class EvaluationCalibrationModel(Base):
    """不可变 Judge Calibration Version 及一致性指标。"""

    __tablename__ = "evaluation_calibrations"

    id: Mapped[str] = mapped_column(String, primary_key=True)                 # 校准记录主键（UUID）
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)  # 所属用户 ID
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False)      # 被校准指标
    judge_version: Mapped[str] = mapped_column(String(160), nullable=False)    # Judge 版本
    dataset_version: Mapped[str] = mapped_column(String(160), nullable=False)  # 校准数据集版本
    human_sample_count: Mapped[int] = mapped_column(Integer, nullable=False)   # 人工标注样本数
    statistics: Mapped[dict] = mapped_column(JSONB, nullable=False)            # 一致性统计指标
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)      # 校准阈值
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # 状态：draft/active 等
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)     # 创建时间


class EvaluationGatePolicyModel(Base):
    """版本化发布门禁策略，生产激活不覆盖历史版本。"""

    __tablename__ = "evaluation_gate_policies"

    id: Mapped[str] = mapped_column(String, primary_key=True)                 # 门禁策略主键（UUID）
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)  # 所属用户 ID
    name: Mapped[str] = mapped_column(String(160), nullable=False)            # 策略名称
    version: Mapped[str] = mapped_column(String(80), nullable=False)          # 策略版本
    hard_gates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 硬门禁规则列表
    metric_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # 指标阈值
    regression_tolerances: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # 回归容忍度
    minimum_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 最小样本量
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # 状态：draft/active 等
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)    # 创建时间

    __table_args__ = (
        # 同一用户下“名称+版本”唯一，历史版本不可覆盖
        UniqueConstraint(
            "user_id", "name", "version", name="uq_evaluation_gate_owner_version"
        ),
    )


class EvaluationGateResultModel(Base):
    """一次不可变门禁检查结果，供 Prompt 发布审计和回放。"""

    __tablename__ = "evaluation_gate_results"

    id: Mapped[str] = mapped_column(String, primary_key=True)                 # 门禁结果主键（UUID）
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)  # 所属用户 ID
    evaluation_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )  # 所属评测运行；随运行删除级联删除
    gate_policy_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_gate_policies.id", ondelete="RESTRICT"), nullable=False
    )  # 引用的门禁策略；被引用时禁止删除
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)             # 是否通过
    blocked_by: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 阻塞原因列表
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # 检查明细
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)    # 创建时间
