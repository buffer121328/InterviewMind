"""Agent 评测中心 HTTP 请求、响应和安全边界模型。"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.schemas.schemas import ApiConfig
from app.security.security import redact_secret_text


class _EvaluationRequest(BaseModel):
    """禁止未知字段的 Evaluation API 请求基类。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvaluationCaseCreateRequest(_EvaluationRequest):
    """一个版本化案例的输入、期望事实、工具和状态机约束。"""

    case_key: str = Field(min_length=1, max_length=160, description="案例唯一标识")
    category: str = Field(min_length=1, max_length=120, description="案例分类")
    input: dict[str, JsonValue] = Field(description="评测输入")
    expected_output: JsonValue | None = Field(default=None, description="期望输出")
    expected_facts: list[JsonValue] = Field(default_factory=list, max_length=200, description="期望出现的事实")
    forbidden_claims: list[JsonValue] = Field(default_factory=list, max_length=200, description="禁止出现的主张")
    expected_tool_calls: list[str] = Field(default_factory=list, max_length=100, description="期望的工具调用")
    allowed_tool_calls: list[str] = Field(default_factory=list, max_length=100, description="允许的工具调用")
    required_state_transitions: list[str] = Field(default_factory=list, max_length=100, description="必须经历的状态迁移")
    forbidden_state_transitions: list[str] = Field(default_factory=list, max_length=100, description="禁止的状态迁移")
    quality_rubric: dict[str, JsonValue] = Field(default_factory=dict, description="质量评分细则")
    retrieval_context: list[str] = Field(default_factory=list, max_length=100, description="检索上下文")
    evidence_refs: list[str] = Field(default_factory=list, max_length=200, description="证据引用")
    tags: list[str] = Field(default_factory=list, max_length=40, description="标签")
    severity: Literal["low", "medium", "high", "critical"] = Field(default="medium", description="严重级别")
    latency_budget_ms: int | None = Field(default=None, ge=1, le=3_600_000, description="延迟预算（毫秒）")
    token_budget: int | None = Field(default=None, ge=1, le=10_000_000, description="Token 预算")
    fault_injection: dict[str, JsonValue] | None = Field(default=None, description="故障注入配置")

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, value: list[str]) -> list[str]:
        """只允许保存不含正文、凭据或空白字符的稳定证据引用。"""

        normalized = list(dict.fromkeys(value))
        for item in normalized:
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@#-]{0,255}", item)
                or redact_secret_text(item) != item
                or "cookie" in item.lower()
            ):
                raise ValueError("unsafe evaluation evidence reference")
        return normalized


class EvaluationDatasetCreateRequest(_EvaluationRequest):
    """创建不可变版本数据集及其加密案例。"""

    name: str = Field(min_length=1, max_length=160, description="数据集名称")
    version: str = Field(min_length=1, max_length=80, description="版本号")
    source: str = Field(default="manual", min_length=1, max_length=80, description="来源")
    cases: list[EvaluationCaseCreateRequest] = Field(min_length=1, max_length=5000, description="案例列表")


class EvaluationDatasetStatusRequest(_EvaluationRequest):
    """推进 Dataset Version 生命周期，但不允许回退或原地修改案例。"""

    status: Literal["annotating", "calibrated", "retired"] = Field(description="目标状态")


class EvaluationSuiteCreateRequest(_EvaluationRequest):
    """创建关联 Agent、Dataset、Rubric 和可选门禁策略的套件。"""

    name: str = Field(min_length=1, max_length=160, description="套件名称")
    agent_name: str = Field(min_length=1, max_length=160, description="目标 Agent 名称")
    description: str | None = Field(default=None, max_length=2000, description="套件描述")
    dataset_version_id: str = Field(min_length=1, max_length=160, description="数据集版本 ID")
    rubric_version: str = Field(min_length=1, max_length=160, description="评分细则版本")
    gate_policy_id: str | None = Field(default=None, max_length=160, description="门禁策略 ID")


class EvaluationRunCreateRequest(_EvaluationRequest):
    """创建有预算、并发和重复次数上限的真实 Agent 评测任务。"""

    suite_id: str = Field(min_length=1, max_length=160, description="套件 ID")
    agent_version: str = Field(default="production", min_length=1, max_length=160, description="Agent 版本")
    prompt_name: str | None = Field(default=None, max_length=160, description="提示词名称")
    prompt_version: str | None = Field(default=None, max_length=160, description="提示词版本")
    baseline_run_id: str | None = Field(default=None, max_length=160, description="基线运行 ID")
    model_config_hash: str = Field(min_length=1, max_length=256, description="模型配置哈希")
    api_config: dict[str, JsonValue] = Field(default_factory=dict, description="模型 API 配置")
    repetition_count: int = Field(default=1, ge=1, le=10, description="重复运行次数")
    max_concurrency: int = Field(default=2, ge=1, le=10, description="最大并发数")
    max_budget_usd: float = Field(gt=0, le=1000, description="最大预算（美元）")
    max_cases: int | None = Field(default=None, ge=1, le=5000, description="最大案例数")
    case_ids: list[str] = Field(default_factory=list, max_length=5000, description="指定案例 ID 列表")
    include_judges: bool = Field(default=False, description="是否包含评测器")
    human_review_rate: float = Field(default=0.0, ge=0, le=1, description="人工复核比例")


class EvaluationQuickRunRequest(_EvaluationRequest):
    """用现有模型设置和服务端内置资产创建一键评测运行。"""

    agent_name: Literal[
        "interview_planner",
        "interview_turn",
        "interview_scoring",
        "resume_optimizer",
        "resume_analyzer",
    ] = Field(description="目标 Agent 名称")
    mode: Literal["quick", "standard", "release"] = Field(default="quick", description="运行模式")
    api_config: ApiConfig = Field(description="模型 API 配置")
    prompt_name: str | None = Field(default=None, min_length=1, max_length=160, description="提示词名称")
    prompt_version: str | None = Field(default=None, min_length=1, max_length=160, description="提示词版本")
    compare_production: bool = Field(default=False, description="是否对比生产版本")


class EvaluationReviewRequest(_EvaluationRequest):
    """把运行中的指定案例或失败案例加入人工复核队列。"""

    case_run_ids: list[str] = Field(default_factory=list, max_length=5000, description="案例运行 ID 列表")
    failed_only: bool = Field(default=True, description="是否仅复核失败案例")


class EvidenceSpan(_EvaluationRequest):
    """输出证据区间；文本只允许业务证据，不允许认证材料。"""

    start: int = Field(ge=0, description="证据区间起始偏移")
    end: int = Field(gt=0, description="证据区间结束偏移")
    text: str = Field(min_length=1, max_length=2000, description="证据文本")

    @field_validator("text")
    @classmethod
    def reject_sensitive_text(cls, value: str) -> str:
        """拒绝包含可用密钥的证据文本。"""

        if redact_secret_text(value) != value or "cookie=" in value.lower():
            raise ValueError("sensitive evidence text is not allowed")
        return value


class EvaluationAnnotationCreateRequest(_EvaluationRequest):
    """追加二元、标量、分类、Pairwise 或证据区间标注。"""

    rubric_version: str = Field(min_length=1, max_length=160, description="评分细则版本")
    annotation_type: Literal["binary", "scalar", "categorical", "pairwise", "evidence"] = Field(description="标注类型")
    metric_name: str = Field(min_length=1, max_length=200, description="指标名称")
    value: JsonValue = Field(description="标注值")
    labels: list[str] = Field(default_factory=list, max_length=40, description="分类标签")
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list, max_length=200, description="证据区间列表")
    comment: str | None = Field(default=None, max_length=2000, description="备注")
    confidence: float | None = Field(default=None, ge=0, le=1, description="置信度")
    reviewer_key: str | None = Field(default=None, min_length=1, max_length=120, description="复核人标识")
    blind: bool = Field(default=True, description="是否盲审")

    @field_validator("comment")
    @classmethod
    def reject_sensitive_comment(cls, value: str | None) -> str | None:
        """拒绝在备注中保存凭据。"""

        if value and redact_secret_text(value) != value:
            raise ValueError("sensitive annotation comment is not allowed")
        return value


class EvaluationAdjudicationRequest(_EvaluationRequest):
    """专家对 conflicted 标注追加裁决 revision。"""

    metric_name: str = Field(min_length=1, max_length=200, description="指标名称")
    value: JsonValue = Field(description="裁决值")
    comment: str | None = Field(default=None, max_length=2000, description="裁决备注")


class EvaluationCandidateDatasetRequest(_EvaluationRequest):
    """把人工确认的失败案例追加到一个新的 Dataset Version。"""

    name: str = Field(min_length=1, max_length=160, description="数据集名称")
    version: str = Field(min_length=1, max_length=80, description="版本号")
    case_key: str | None = Field(default=None, min_length=1, max_length=160, description="案例唯一标识")
    category: str = Field(default="regression", min_length=1, max_length=120, description="案例分类")
    expected_output: JsonValue | None = Field(default=None, description="期望输出")
    expected_facts: list[JsonValue] = Field(default_factory=list, max_length=200, description="期望出现的事实")
    forbidden_claims: list[JsonValue] = Field(default_factory=list, max_length=200, description="禁止出现的主张")
    tags: list[str] = Field(default_factory=lambda: ["candidate", "regression"], max_length=40, description="标签")
    severity: Literal["low", "medium", "high", "critical"] = Field(default="high", description="严重级别")


class EvaluationOnlineSampleRequest(_EvaluationRequest):
    """对已脱敏生产 Trace 计算确定性/Judge/人工抽样决策。"""

    trace_id: str = Field(min_length=1, max_length=256, description="生产 Trace ID")
    risk_level: Literal["low", "medium", "high", "critical"] = Field(default="medium", description="风险级别")
    trace: dict[str, JsonValue] = Field(description="脱敏后的 Trace 数据")


class EvaluationCalibrationCreateRequest(_EvaluationRequest):
    """从 Judge 与人工样本创建不可变 Calibration Version。"""

    metric_name: str = Field(min_length=1, max_length=200, description="指标名称")
    judge_version: str = Field(min_length=1, max_length=160, description="评测器版本")
    dataset_version: str = Field(min_length=1, max_length=160, description="数据集版本")
    judge_scores: list[float] = Field(min_length=2, max_length=100_000, description="评测器得分列表")
    human_scores: list[float] = Field(min_length=2, max_length=100_000, description="人工得分列表")
    judge_binary: list[bool] = Field(default_factory=list, description="评测器二分类结果")
    human_binary: list[bool] = Field(default_factory=list, description="人工二分类结果")
    severe_mask: list[bool] = Field(default_factory=list, description="严重样本掩码")
    threshold: float | None = Field(default=None, description="阈值")


class EvaluationCalibrationSimulateRequest(_EvaluationRequest):
    """在不修改生产配置的情况下回放一个候选阈值。"""

    threshold: float = Field(description="候选阈值")
    scores: list[float] = Field(min_length=1, max_length=100_000, description="得分列表")
    expected_pass: list[bool] = Field(min_length=1, max_length=100_000, description="期望通过结果")


class EvaluationGateMetricThreshold(_EvaluationRequest):
    """一个带方向的门禁阈值；支持越大越好、越小越好和零容忍。"""

    value: float = Field(description="阈值数值")
    comparison: Literal["gte", "lte", "eq"] = Field(default="gte", description="比较方向")


class EvaluationGatePolicyCreateRequest(_EvaluationRequest):
    """创建版本化 Gate Policy 草稿。"""

    name: str = Field(min_length=1, max_length=160, description="策略名称")
    version: str = Field(min_length=1, max_length=80, description="版本号")
    hard_gates: list[str] = Field(default_factory=list, max_length=100, description="硬门禁指标列表")
    metric_thresholds: dict[str, float | EvaluationGateMetricThreshold] = Field(
        default_factory=dict, description="指标阈值映射"
    )
    regression_tolerances: dict[str, float | EvaluationGateMetricThreshold] = Field(
        default_factory=dict, description="回归容忍度映射"
    )
    minimum_sample_size: int = Field(default=20, ge=1, le=1_000_000, description="最小样本量")
    status: Literal["draft", "active", "retired"] = Field(default="draft", description="策略状态")


class EvaluationPage(BaseModel):
    """统一分页响应。"""

    items: list[dict[str, Any]] = Field(description="当前页数据项")
    total: int = Field(ge=0, description="总数")
    limit: int = Field(ge=1, description="每页条数")
    offset: int = Field(ge=0, description="偏移量")


class InterviewEvaluationSourceSnapshot(_EvaluationRequest):
    """由服务端从历史面试记录冻结的权威评测输入。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    attempt_id: int = Field(ge=1, description="尝试 ID")
    session_id: str = Field(min_length=1, max_length=200, description="会话 ID")
    capability: Literal["interview_turn", "interview_scoring"] = Field(description="能力类型")
    question: str = Field(min_length=1, max_length=20_000, description="问题文本")
    answer: str = Field(min_length=1, max_length=100_000, description="回答文本")
    input: dict[str, JsonValue] = Field(description="冻结的评测输入")
    evidence_refs: list[str] = Field(min_length=1, max_length=20, description="证据引用")
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$", description="源数据哈希")


class InterviewEvaluationDraftAnnotation(_EvaluationRequest):
    """模型可建议且人工可编辑的非权威评测字段。"""

    case_key: str = Field(min_length=1, max_length=160, description="案例唯一标识")
    category: str = Field(min_length=1, max_length=120, description="案例分类")
    expected_facts: list[JsonValue] = Field(default_factory=list, max_length=200, description="期望出现的事实")
    forbidden_claims: list[JsonValue] = Field(default_factory=list, max_length=200, description="禁止出现的主张")
    quality_rubric: dict[str, JsonValue] = Field(default_factory=dict, description="质量评分细则")
    tags: list[str] = Field(default_factory=list, max_length=36, description="标签")
    severity: Literal["low", "medium", "high", "critical"] = Field(default="medium", description="严重级别")
    explanation: str = Field(default="", max_length=4_000, description="生成说明")


class InterviewEvaluationDraftCase(_EvaluationRequest):
    """单个历史问答的可审阅草稿及逐案例校验状态。"""

    attempt_id: int = Field(ge=1, description="尝试 ID")
    session_id: str = Field(min_length=1, max_length=200, description="会话 ID")
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$", description="源数据哈希")
    question: str = Field(min_length=1, max_length=20_000, description="问题文本")
    answer: str = Field(min_length=1, max_length=100_000, description="回答文本")
    frozen_input: dict[str, JsonValue] = Field(description="冻结的评测输入")
    evidence_refs: list[str] = Field(min_length=1, max_length=20, description="证据引用")
    validation_status: Literal["valid", "needs_review", "failed"] = Field(description="校验状态")
    annotation: InterviewEvaluationDraftAnnotation | None = Field(default=None, description="草稿标注")
    failure_reason: str | None = Field(default=None, max_length=500, description="失败原因")
    model: dict[str, JsonValue] = Field(default_factory=dict, description="模型输出元数据")

    @field_validator("failure_reason")
    @classmethod
    def validate_failure_reason(cls, value: str | None) -> str | None:
        """失败原因必须已脱敏，避免把供应商异常原文写入 AgentRun。"""

        if value is not None and redact_secret_text(value) != value:
            raise ValueError("unsafe draft failure reason")
        return value


class InterviewEvaluationDraftResult(_EvaluationRequest):
    """可持久化在 AgentRun.result 中的安全草稿结果。"""

    capability: Literal["interview_turn", "interview_scoring"] = Field(description="能力类型")
    status: Literal["needs_review"] = Field(default="needs_review", description="草稿状态")
    selected_count: int = Field(ge=0, le=50, description="选中案例数")
    valid_count: int = Field(ge=0, le=50, description="有效案例数")
    failed_count: int = Field(ge=0, le=50, description="失败案例数")
    cases: list[InterviewEvaluationDraftCase] = Field(default_factory=list, max_length=50, description="案例草稿列表")


class InterviewEvaluationDraftRequest(_EvaluationRequest):
    """提交历史问答整理任务；只接收模型配置引用，不接收明文凭据。"""

    attempt_ids: list[int] = Field(min_length=1, max_length=50, description="尝试 ID 列表")
    capability: Literal["interview_turn", "interview_scoring"] = Field(description="能力类型")
    api_config: dict[str, JsonValue] = Field(description="模型 API 配置")

    @field_validator("attempt_ids")
    @classmethod
    def validate_attempt_ids(cls, value: list[int]) -> list[int]:
        """保持用户选择顺序并拒绝重复或非法 ID。"""

        if any(item < 1 for item in value) or len(set(value)) != len(value):
            raise ValueError("attempt_ids must contain unique positive integers")
        return value

    @field_validator("api_config")
    @classmethod
    def reject_plaintext_credentials(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """队列 payload 只保存 credential reference，禁止明文 API Key。"""

        def walk(item: JsonValue) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if key.lower() in {"api_key", "apikey", "authorization", "cookie", "password", "secret", "token"}:
                        raise ValueError("plaintext model credentials are not accepted")
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)

        walk(value)
        return value


class InterviewEvaluationReviewCase(_EvaluationRequest):
    """人工审阅后的单案例选择和可编辑生成字段。"""

    attempt_id: int = Field(ge=1, description="尝试 ID")
    reviewed: bool = Field(description="是否已审阅")
    included: bool = Field(default=True, description="是否纳入")
    annotation: InterviewEvaluationDraftAnnotation | None = Field(default=None, description="草稿标注")

    @model_validator(mode="after")
    def require_review_for_included_case(self):
        """所有纳入案例必须已审阅且有合法标注。"""

        if self.included and (not self.reviewed or self.annotation is None):
            raise ValueError("included cases must be reviewed and annotated")
        return self


class InterviewEvaluationConfirmRequest(_EvaluationRequest):
    """把人工确认的草稿原子创建为 draft Candidate Dataset。"""

    name: str = Field(min_length=1, max_length=160, description="数据集名称")
    version: str = Field(min_length=1, max_length=80, description="版本号")
    cases: list[InterviewEvaluationReviewCase] = Field(min_length=1, max_length=50, description="审阅案例列表")

    @field_validator("cases")
    @classmethod
    def require_included_case(
        cls, value: list[InterviewEvaluationReviewCase]
    ) -> list[InterviewEvaluationReviewCase]:
        """确认请求至少包含一个已审阅并纳入的数据案例。"""

        if not any(item.included for item in value):
            raise ValueError("at least one reviewed case must be included")
        ids = [item.attempt_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate attempt review")
        return value


class InterviewEvaluationRetryRequest(_EvaluationRequest):
    """仅重试一个已完成草稿中失败的选定案例。"""

    attempt_ids: list[int] = Field(min_length=1, max_length=50, description="尝试 ID 列表")
    api_config: dict[str, JsonValue] = Field(description="模型 API 配置")

    @field_validator("attempt_ids")
    @classmethod
    def validate_attempt_ids(cls, value: list[int]) -> list[int]:
        """重试列表必须为唯一正整数。"""

        if any(item < 1 for item in value) or len(set(value)) != len(value):
            raise ValueError("attempt_ids must contain unique positive integers")
        return value

    @field_validator("api_config")
    @classmethod
    def reject_plaintext_credentials(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        """重试也只接收模型凭据引用。"""

        return InterviewEvaluationDraftRequest.reject_plaintext_credentials(value)
