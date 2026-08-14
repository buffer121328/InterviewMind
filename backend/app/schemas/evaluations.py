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

    case_key: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=120)
    input: dict[str, JsonValue]
    expected_output: JsonValue | None = None
    expected_facts: list[JsonValue] = Field(default_factory=list, max_length=200)
    forbidden_claims: list[JsonValue] = Field(default_factory=list, max_length=200)
    expected_tool_calls: list[str] = Field(default_factory=list, max_length=100)
    allowed_tool_calls: list[str] = Field(default_factory=list, max_length=100)
    required_state_transitions: list[str] = Field(default_factory=list, max_length=100)
    forbidden_state_transitions: list[str] = Field(default_factory=list, max_length=100)
    quality_rubric: dict[str, JsonValue] = Field(default_factory=dict)
    retrieval_context: list[str] = Field(default_factory=list, max_length=100)
    evidence_refs: list[str] = Field(default_factory=list, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=40)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    latency_budget_ms: int | None = Field(default=None, ge=1, le=3_600_000)
    token_budget: int | None = Field(default=None, ge=1, le=10_000_000)
    fault_injection: dict[str, JsonValue] | None = None

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

    name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    source: str = Field(default="manual", min_length=1, max_length=80)
    cases: list[EvaluationCaseCreateRequest] = Field(min_length=1, max_length=5000)


class EvaluationDatasetStatusRequest(_EvaluationRequest):
    """推进 Dataset Version 生命周期，但不允许回退或原地修改案例。"""

    status: Literal["annotating", "calibrated", "retired"]


class EvaluationSuiteCreateRequest(_EvaluationRequest):
    """创建关联 Agent、Dataset、Rubric 和可选门禁策略的套件。"""

    name: str = Field(min_length=1, max_length=160)
    agent_name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    dataset_version_id: str = Field(min_length=1, max_length=160)
    rubric_version: str = Field(min_length=1, max_length=160)
    gate_policy_id: str | None = Field(default=None, max_length=160)


class EvaluationRunCreateRequest(_EvaluationRequest):
    """创建有预算、并发和重复次数上限的真实 Agent 评测任务。"""

    suite_id: str = Field(min_length=1, max_length=160)
    agent_version: str = Field(default="production", min_length=1, max_length=160)
    prompt_name: str | None = Field(default=None, max_length=160)
    prompt_version: str | None = Field(default=None, max_length=160)
    baseline_run_id: str | None = Field(default=None, max_length=160)
    model_config_hash: str = Field(min_length=1, max_length=256)
    api_config: dict[str, JsonValue] = Field(default_factory=dict)
    repetition_count: int = Field(default=1, ge=1, le=10)
    max_concurrency: int = Field(default=2, ge=1, le=10)
    max_budget_usd: float = Field(gt=0, le=1000)
    max_cases: int | None = Field(default=None, ge=1, le=5000)
    case_ids: list[str] = Field(default_factory=list, max_length=5000)
    include_judges: bool = False
    human_review_rate: float = Field(default=0.0, ge=0, le=1)


class EvaluationQuickRunRequest(_EvaluationRequest):
    """用现有模型设置和服务端内置资产创建一键评测运行。"""

    agent_name: Literal[
        "interview_planner",
        "interview_turn",
        "interview_scoring",
        "resume_optimizer",
        "resume_analyzer",
    ]
    mode: Literal["quick", "standard", "release"] = "quick"
    api_config: ApiConfig
    prompt_name: str | None = Field(default=None, min_length=1, max_length=160)
    prompt_version: str | None = Field(default=None, min_length=1, max_length=160)
    compare_production: bool = False


class EvaluationReviewRequest(_EvaluationRequest):
    """把运行中的指定案例或失败案例加入人工复核队列。"""

    case_run_ids: list[str] = Field(default_factory=list, max_length=5000)
    failed_only: bool = True


class EvidenceSpan(_EvaluationRequest):
    """输出证据区间；文本只允许业务证据，不允许认证材料。"""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def reject_sensitive_text(cls, value: str) -> str:
        """拒绝包含可用密钥的证据文本。"""

        if redact_secret_text(value) != value or "cookie=" in value.lower():
            raise ValueError("sensitive evidence text is not allowed")
        return value


class EvaluationAnnotationCreateRequest(_EvaluationRequest):
    """追加二元、标量、分类、Pairwise 或证据区间标注。"""

    rubric_version: str = Field(min_length=1, max_length=160)
    annotation_type: Literal["binary", "scalar", "categorical", "pairwise", "evidence"]
    metric_name: str = Field(min_length=1, max_length=200)
    value: JsonValue
    labels: list[str] = Field(default_factory=list, max_length=40)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list, max_length=200)
    comment: str | None = Field(default=None, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    reviewer_key: str | None = Field(default=None, min_length=1, max_length=120)
    blind: bool = True

    @field_validator("comment")
    @classmethod
    def reject_sensitive_comment(cls, value: str | None) -> str | None:
        """拒绝在备注中保存凭据。"""

        if value and redact_secret_text(value) != value:
            raise ValueError("sensitive annotation comment is not allowed")
        return value


class EvaluationAdjudicationRequest(_EvaluationRequest):
    """专家对 conflicted 标注追加裁决 revision。"""

    metric_name: str = Field(min_length=1, max_length=200)
    value: JsonValue
    comment: str | None = Field(default=None, max_length=2000)


class EvaluationCandidateDatasetRequest(_EvaluationRequest):
    """把人工确认的失败案例追加到一个新的 Dataset Version。"""

    name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    case_key: str | None = Field(default=None, min_length=1, max_length=160)
    category: str = Field(default="regression", min_length=1, max_length=120)
    expected_output: JsonValue | None = None
    expected_facts: list[JsonValue] = Field(default_factory=list, max_length=200)
    forbidden_claims: list[JsonValue] = Field(default_factory=list, max_length=200)
    tags: list[str] = Field(default_factory=lambda: ["candidate", "regression"], max_length=40)
    severity: Literal["low", "medium", "high", "critical"] = "high"


class EvaluationOnlineSampleRequest(_EvaluationRequest):
    """对已脱敏生产 Trace 计算确定性/Judge/人工抽样决策。"""

    trace_id: str = Field(min_length=1, max_length=256)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    trace: dict[str, JsonValue]


class EvaluationCalibrationCreateRequest(_EvaluationRequest):
    """从 Judge 与人工样本创建不可变 Calibration Version。"""

    metric_name: str = Field(min_length=1, max_length=200)
    judge_version: str = Field(min_length=1, max_length=160)
    dataset_version: str = Field(min_length=1, max_length=160)
    judge_scores: list[float] = Field(min_length=2, max_length=100_000)
    human_scores: list[float] = Field(min_length=2, max_length=100_000)
    judge_binary: list[bool] = Field(default_factory=list)
    human_binary: list[bool] = Field(default_factory=list)
    severe_mask: list[bool] = Field(default_factory=list)
    threshold: float | None = None


class EvaluationCalibrationSimulateRequest(_EvaluationRequest):
    """在不修改生产配置的情况下回放一个候选阈值。"""

    threshold: float
    scores: list[float] = Field(min_length=1, max_length=100_000)
    expected_pass: list[bool] = Field(min_length=1, max_length=100_000)


class EvaluationGateMetricThreshold(_EvaluationRequest):
    """一个带方向的门禁阈值；支持越大越好、越小越好和零容忍。"""

    value: float
    comparison: Literal["gte", "lte", "eq"] = "gte"


class EvaluationGatePolicyCreateRequest(_EvaluationRequest):
    """创建版本化 Gate Policy 草稿。"""

    name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    hard_gates: list[str] = Field(default_factory=list, max_length=100)
    metric_thresholds: dict[str, float | EvaluationGateMetricThreshold] = Field(
        default_factory=dict
    )
    regression_tolerances: dict[str, float | EvaluationGateMetricThreshold] = Field(
        default_factory=dict
    )
    minimum_sample_size: int = Field(default=20, ge=1, le=1_000_000)
    status: Literal["draft", "active", "retired"] = "draft"


class EvaluationPage(BaseModel):
    """统一分页响应。"""

    items: list[dict[str, Any]]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class InterviewEvaluationSourceSnapshot(_EvaluationRequest):
    """由服务端从历史面试记录冻结的权威评测输入。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    attempt_id: int = Field(ge=1)
    session_id: str = Field(min_length=1, max_length=200)
    capability: Literal["interview_turn", "interview_scoring"]
    question: str = Field(min_length=1, max_length=20_000)
    answer: str = Field(min_length=1, max_length=100_000)
    input: dict[str, JsonValue]
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class InterviewEvaluationDraftAnnotation(_EvaluationRequest):
    """模型可建议且人工可编辑的非权威评测字段。"""

    case_key: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=120)
    expected_facts: list[JsonValue] = Field(default_factory=list, max_length=200)
    forbidden_claims: list[JsonValue] = Field(default_factory=list, max_length=200)
    quality_rubric: dict[str, JsonValue] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=36)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    explanation: str = Field(default="", max_length=4_000)


class InterviewEvaluationDraftCase(_EvaluationRequest):
    """单个历史问答的可审阅草稿及逐案例校验状态。"""

    attempt_id: int = Field(ge=1)
    session_id: str = Field(min_length=1, max_length=200)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    question: str = Field(min_length=1, max_length=20_000)
    answer: str = Field(min_length=1, max_length=100_000)
    frozen_input: dict[str, JsonValue]
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    validation_status: Literal["valid", "needs_review", "failed"]
    annotation: InterviewEvaluationDraftAnnotation | None = None
    failure_reason: str | None = Field(default=None, max_length=500)
    model: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("failure_reason")
    @classmethod
    def validate_failure_reason(cls, value: str | None) -> str | None:
        """失败原因必须已脱敏，避免把供应商异常原文写入 AgentRun。"""

        if value is not None and redact_secret_text(value) != value:
            raise ValueError("unsafe draft failure reason")
        return value


class InterviewEvaluationDraftResult(_EvaluationRequest):
    """可持久化在 AgentRun.result 中的安全草稿结果。"""

    capability: Literal["interview_turn", "interview_scoring"]
    status: Literal["needs_review"] = "needs_review"
    selected_count: int = Field(ge=0, le=50)
    valid_count: int = Field(ge=0, le=50)
    failed_count: int = Field(ge=0, le=50)
    cases: list[InterviewEvaluationDraftCase] = Field(default_factory=list, max_length=50)


class InterviewEvaluationDraftRequest(_EvaluationRequest):
    """提交历史问答整理任务；只接收模型配置引用，不接收明文凭据。"""

    attempt_ids: list[int] = Field(min_length=1, max_length=50)
    capability: Literal["interview_turn", "interview_scoring"]
    api_config: dict[str, JsonValue]

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

    attempt_id: int = Field(ge=1)
    reviewed: bool
    included: bool = True
    annotation: InterviewEvaluationDraftAnnotation | None = None

    @model_validator(mode="after")
    def require_review_for_included_case(self):
        """所有纳入案例必须已审阅且有合法标注。"""

        if self.included and (not self.reviewed or self.annotation is None):
            raise ValueError("included cases must be reviewed and annotated")
        return self


class InterviewEvaluationConfirmRequest(_EvaluationRequest):
    """把人工确认的草稿原子创建为 draft Candidate Dataset。"""

    name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    cases: list[InterviewEvaluationReviewCase] = Field(min_length=1, max_length=50)

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

    attempt_ids: list[int] = Field(min_length=1, max_length=50)
    api_config: dict[str, JsonValue]

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
