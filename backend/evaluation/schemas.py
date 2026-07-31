"""项目级 Agent 评测中间记录与可审计分数契约。"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class EvalToolEffect(str, Enum):
    """工具对业务世界产生的副作用级别，与运行时 ToolEffect 保持一致。"""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"


class EvalToolStatus(str, Enum):
    """评测轨迹中的工具调用终态或中间状态。"""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class EvalApprovalStatus(str, Enum):
    """外部操作或高风险写操作的人工确认状态。"""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EvalExternalIOStatus(str, Enum):
    """外部依赖调用的状态，不把依赖成功冒充为业务成功。"""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EvalScoreStatus(str, Enum):
    """单项评测结果状态，硬门禁只接受明确通过。"""

    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    REVIEW_REQUIRED = "review_required"


class ScoreSource(str, Enum):
    """分数来源，用于区分确定性、Judge 和人工事实。"""

    DETERMINISTIC = "deterministic"
    JUDGE = "judge"
    HUMAN = "human"


class EvalSensitiveDataStatus(str, Enum):
    """敏感信息在进入持久化记录前的处置结果。"""

    REDACTED = "redacted"
    HASHED = "hashed"
    BLOCKED = "blocked"
    EXPOSED = "exposed"


class EvalFactVerdict(str, Enum):
    """简历或业务事实原子 claim 的证据判定。"""

    SUPPORTED = "supported"
    PARAPHRASED = "paraphrased"
    INFERRED_REQUIRES_CONFIRMATION = "inferred_requires_confirmation"
    CONTRADICTED = "contradicted"
    FABRICATED = "fabricated"


class HardGateCategory(str, Enum):
    """不能被平均分抵消的确定性失败类别。"""

    CROSS_USER_ACCESS = "hard_gate.cross_user_access"
    UNAPPROVED_EXTERNAL_ACTION = "hard_gate.unapproved_external_action"
    CREDENTIAL_LEAK = "hard_gate.credential_leak"
    PROMPT_INJECTION_SUCCESS = "hard_gate.prompt_injection_success"
    HIGH_SEVERITY_RESUME_FABRICATION = "hard_gate.high_severity_resume_fabrication"
    DUPLICATE_EXTERNAL_SIDE_EFFECT = "hard_gate.duplicate_external_side_effect"
    POST_CANCEL_EXTERNAL_WRITE = "hard_gate.post_cancel_external_write"
    CHECKPOINT_INTEGRITY_VIOLATION = "hard_gate.checkpoint_integrity_violation"
    EVALUATION_DATA_CONTAMINATION = "hard_gate.evaluation_data_contamination"


class _EvalModel(BaseModel):
    """统一启用严格字段和不可变语义的评测数据基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvalTokenUsage(_EvalModel):
    """记录模型调用汇总 Token；不保存请求或响应正文。"""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> EvalTokenUsage:
        """拒绝小于输入输出之和的总量，避免报告出现不可能的统计。"""

        if self.total_tokens is not None:
            minimum = self.input_tokens + self.output_tokens
            if self.total_tokens < minimum:
                raise ValueError("total_tokens must cover input_tokens and output_tokens")
        return self


class EvalStep(_EvalModel):
    """Agent 工作流中的稳定步骤摘要，不承载原始业务 payload。"""

    sequence: int = Field(ge=0)
    stage: str = Field(min_length=1, max_length=120)
    status: str = Field(min_length=1, max_length=64)
    duration_ms: int | None = Field(default=None, ge=0)
    checkpoint_written: bool = False
    recovery_source: str | None = Field(default=None, max_length=160)
    summary: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """确保步骤摘要不包含可直接使用的认证材料。"""

        _raise_for_sensitive_payload(value)
        return value


class EvalToolCall(_EvalModel):
    """工具调用的权限、副作用、审批、重试和幂等审计记录。"""

    call_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    event_type: str = Field(default="tool.completed", min_length=1, max_length=120)
    parent_call_id: str | None = Field(default=None, max_length=160)
    tool_name: str = Field(min_length=1, max_length=160)
    effect: EvalToolEffect = EvalToolEffect.READ
    status: EvalToolStatus
    attempt: int = Field(default=1, ge=1)
    arguments_summary: dict[str, JsonValue] = Field(default_factory=dict)
    result_summary: dict[str, JsonValue] = Field(default_factory=dict)
    required_permissions: tuple[str, ...] = ()
    granted_permissions: tuple[str, ...] = ()
    requires_confirmation: bool = False
    approval_status: EvalApprovalStatus = EvalApprovalStatus.NOT_REQUIRED
    resource_owner_hash: str | None = Field(default=None, max_length=256)
    idempotency_key_hash: str | None = Field(default=None, max_length=256)
    simulated: bool = False
    target_namespace: str | None = Field(default=None, max_length=256)
    latency_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    error_type: str | None = Field(default=None, max_length=160)
    error_category: str | None = Field(default=None, max_length=160)
    evidence_refs: tuple[str, ...] = ()

    @field_validator("arguments_summary", "result_summary")
    @classmethod
    def validate_summaries(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """确保工具参数和结果只保留脱敏摘要。"""

        _raise_for_sensitive_payload(value)
        return value


class EvalRetrieval(_EvalModel):
    """一次 RAG 或 Memory 检索的来源、排名和采用情况。"""

    retrieval_id: str = Field(min_length=1, max_length=160)
    query_fingerprint: str = Field(min_length=1, max_length=256)
    source_type: str = Field(min_length=1, max_length=80)
    source_id_hash: str | None = Field(default=None, max_length=256)
    score: float | None = None
    rank: int | None = Field(default=None, ge=1)
    adopted: bool = False
    strategy: str | None = Field(default=None, max_length=120)
    call_id: str | None = Field(default=None, max_length=160)
    sequence: int | None = Field(default=None, ge=0)
    result_count: int | None = Field(default=None, ge=0)
    empty_result: bool | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_category: str | None = Field(default=None, max_length=160)


class EvalExternalIO(_EvalModel):
    """外部依赖的可用性、耗时和结果计数；不承载请求或响应正文。"""

    call_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    event_type: str = Field(default="external_io.completed", min_length=1, max_length=120)
    parent_call_id: str | None = Field(default=None, max_length=160)
    operation: str = Field(min_length=1, max_length=160)
    dependency: str | None = Field(default=None, max_length=120)
    status: EvalExternalIOStatus
    attempt: int = Field(default=1, ge=1)
    duration_ms: int | None = Field(default=None, ge=0)
    item_count: int | None = Field(default=None, ge=0)
    result_count: int | None = Field(default=None, ge=0)
    query_fingerprint: str | None = Field(default=None, max_length=256)
    adopted: bool | None = None
    error_type: str | None = Field(default=None, max_length=160)
    error_category: str | None = Field(default=None, max_length=160)


class EvalModelCall(_EvalModel):
    """模型成员、fallback、Token、延迟和错误分类摘要。"""

    call_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    model_channel: str = Field(min_length=1, max_length=120)
    model_member_hash: str = Field(min_length=1, max_length=256)
    fallback_index: int = Field(default=0, ge=0)
    input_char_count: int = Field(default=0, ge=0)
    output_char_count: int = Field(default=0, ge=0)
    token_usage: EvalTokenUsage = Field(default_factory=EvalTokenUsage)
    latency_ms: int = Field(default=0, ge=0)
    status: str = Field(default="completed", min_length=1, max_length=64)
    error_classification: str | None = Field(default=None, max_length=160)


class EvalApproval(_EvalModel):
    """人工确认请求及决定的可审计引用。"""

    approval_id: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=160)
    status: EvalApprovalStatus
    requested_sequence: int = Field(ge=0)
    decided_sequence: int | None = Field(default=None, ge=0)
    actor_hash: str | None = Field(default=None, max_length=256)
    call_id: str | None = Field(default=None, max_length=160)
    sequence: int | None = Field(default=None, ge=0)
    event_type: str = Field(default="approval.resolved", min_length=1, max_length=120)
    evidence_refs: tuple[str, ...] = ()


class EvalRunEvent(_EvalModel):
    """AgentRun 的稳定事件序列和阶段摘要。"""

    sequence: int = Field(ge=0)
    stage: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=120)
    status: str | None = Field(default=None, max_length=64)
    payload_summary: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("payload_summary")
    @classmethod
    def validate_payload_summary(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """确保事件只携带脱敏、限域后的摘要字段。"""

        _raise_for_sensitive_payload(value)
        return value


class EvalError(_EvalModel):
    """稳定错误分类和脱敏消息，不保存堆栈或完整请求。"""

    classification: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=300)
    retryable: bool = False

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        """拒绝错误消息中的可用密钥，避免失败链路成为泄漏通道。"""

        _raise_for_sensitive_payload(value)
        return value


class EvalSensitiveDataFinding(_EvalModel):
    """记录敏感数据类型、位置和处置结果，不记录敏感值本身。"""

    kind: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=240)
    status: EvalSensitiveDataStatus
    evidence_refs: tuple[str, ...] = ()


class EvalSecuritySignal(_EvalModel):
    """无法仅由通用轨迹推导时，由安全组件提供的确定性信号。"""

    category: HardGateCategory
    detected: bool
    evidence_refs: tuple[str, ...] = ()


class EvalFactClaim(_EvalModel):
    """简历原子事实的分类结果；仅保存 claim 引用和证据引用。"""

    claim_id: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    verdict: EvalFactVerdict
    severity: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    requires_confirmation: bool = False
    confirmed: bool = False
    evidence_refs: tuple[str, ...] = ()


class EvalScore(_EvalModel):
    """统一自动或人工分数，保留来源、阈值、证据和硬门禁属性。"""

    metric_name: str = Field(min_length=1, max_length=200)
    dimension: str = Field(min_length=1, max_length=120)
    evaluator_name: str = Field(min_length=1, max_length=160)
    source: ScoreSource
    status: EvalScoreStatus
    value: float | None = None
    threshold: float | None = None
    hard_gate: bool = False
    reason_code: str | None = Field(default=None, max_length=160)
    evidence_refs: tuple[str, ...] = ()


class EvalTraceCompleteness(_EvalModel):
    """关键观测证据是否齐全；缺失时进入复核而不是静默通过。"""

    complete: bool = False
    trace_id_present: bool = False
    tracing_disabled: bool = False
    agent_version_present: bool = False
    prompt_version_present: bool = False
    model_config_hash_present: bool = False
    tool_terminal_states_complete: bool = True
    stable_error_categories: bool = True
    external_approval_status_present: bool = True
    agent_run_id_present: bool = False
    sensitive_data_clean: bool = True
    evaluation_namespace_isolated: bool = False
    score: float = Field(default=0.0, ge=0, le=1)
    missing: tuple[str, ...] = ()


class EvalObservabilitySummary(_EvalModel):
    """前端和根 Span 共用的安全观测摘要，不包含单次业务正文。"""

    schema_version: int = Field(default=1, ge=1)
    tool_event_count: int = Field(default=0, ge=0)
    tool_call_summary: dict[str, JsonValue] = Field(default_factory=dict)
    external_io_event_count: int = Field(default=0, ge=0)
    external_io_summary: dict[str, JsonValue] = Field(default_factory=dict)
    approval_event_count: int = Field(default=0, ge=0)
    langfuse_reported: bool | None = None
    langfuse_error: str | None = Field(default=None, max_length=160)
    trace_completeness: EvalTraceCompleteness = Field(default_factory=EvalTraceCompleteness)


class AgentEvalRecord(_EvalModel):
    """Eval Harness 与 DeepEval、Langfuse、人工标注之间的中间记录。"""

    case_id: str = Field(min_length=1, max_length=160)
    dataset_version: str = Field(min_length=1, max_length=160)
    case_version: str | None = Field(default=None, max_length=160)
    agent_name: str = Field(min_length=1, max_length=160)
    agent_version: str = Field(min_length=1, max_length=160)
    prompt_name: str | None = Field(default=None, max_length=160)
    prompt_version: str | None = Field(default=None, max_length=160)
    model_config_hash: str = Field(min_length=1, max_length=256)
    owner_scope_hash: str = Field(min_length=1, max_length=256)
    evaluation_namespace: str = Field(min_length=1, max_length=256)
    trace_id: str | None = Field(default=None, max_length=256)
    agent_run_id: str | None = Field(default=None, max_length=256)
    input_summary: dict[str, JsonValue]
    final_output: JsonValue
    steps: tuple[EvalStep, ...] = ()
    tool_calls: tuple[EvalToolCall, ...] = ()
    retrievals: tuple[EvalRetrieval, ...] = ()
    external_ios: tuple[EvalExternalIO, ...] = ()
    model_calls: tuple[EvalModelCall, ...] = ()
    approvals: tuple[EvalApproval, ...] = ()
    events: tuple[EvalRunEvent, ...] = ()
    sensitive_data_findings: tuple[EvalSensitiveDataFinding, ...] = ()
    security_signals: tuple[EvalSecuritySignal, ...] = ()
    fact_claims: tuple[EvalFactClaim, ...] = ()
    final_status: str = Field(min_length=1, max_length=64)
    latency_ms: int = Field(ge=0)
    input_char_count: int = Field(default=0, ge=0)
    output_char_count: int = Field(default=0, ge=0)
    checkpoint_write_count: int = Field(default=0, ge=0)
    recovery_count: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    token_usage: EvalTokenUsage = Field(default_factory=EvalTokenUsage)
    error: EvalError | None = None
    observability: EvalObservabilitySummary = Field(default_factory=EvalObservabilitySummary)

    @field_validator("input_summary", "final_output")
    @classmethod
    def validate_persisted_payload(cls, value: Any) -> Any:
        """拒绝把可用凭据或认证头写入统一评测记录。"""

        _raise_for_sensitive_payload(value)
        return value

    @model_validator(mode="after")
    def validate_trace_identity(self) -> AgentEvalRecord:
        """保证同类轨迹 ID 和事件 sequence 唯一，避免审计引用歧义。"""

        _require_unique((item.call_id for item in self.tool_calls), "tool call_id")
        _require_unique((item.call_id for item in self.external_ios), "external IO call_id")
        _require_unique((item.call_id for item in self.model_calls), "model call_id")
        _require_unique((item.approval_id for item in self.approvals), "approval_id")
        _require_unique((item.sequence for item in self.events), "event sequence")
        return self


_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "proxy_authorization",
        "token",
        "secret",
        "password",
        "cookie",
        "set_cookie",
    }
)
_SAFE_SECRET_VALUES = frozenset({"***REDACTED***", "[REDACTED]", "REDACTED"})
_SECRET_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"api[_-]?key\s*[:=]\s*(?!\*\*\*REDACTED\*\*\*|\[REDACTED\])\S+",
        r"authorization\s*[:=]\s*bearer\s+(?!\*\*\*REDACTED\*\*\*|\[REDACTED\])\S+",
        r"cookie\s*[:=]\s*(?!\*\*\*REDACTED\*\*\*|\[REDACTED\])\S+",
        r"\bsk-[A-Za-z0-9_-]{12,}\b",
    )
)


def _raise_for_sensitive_payload(value: Any) -> None:
    """拒绝未脱敏认证材料；异常只报告位置规则，不回显原值。"""

    if _contains_sensitive_payload(value):
        raise ValueError("sensitive evaluation payload must be redacted or hashed")


def _contains_sensitive_payload(value: Any) -> bool:
    """递归检查评测载荷是否仍包含可直接使用的凭据。"""

    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS and not _is_safe_secret_value(item):
                return True
            if _contains_sensitive_payload(item):
                return True
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_sensitive_payload(item) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_PATTERNS)
    return False


def _is_safe_secret_value(value: Any) -> bool:
    """允许明确脱敏标记、空值或单向哈希出现在敏感键下。"""

    if value is None:
        return True
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    return normalized in _SAFE_SECRET_VALUES or normalized.startswith("sha256:")


def _require_unique(values: Any, label: str) -> None:
    """校验稳定标识唯一，避免报告和证据引用指向多个对象。"""

    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"duplicate {label}")
