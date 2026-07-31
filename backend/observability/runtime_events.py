"""Agent 运行时 Tool、外部 IO 与审批事件的统一安全契约。

本模块只定义稳定事件、状态校验和存储投影，不直接调用 Langfuse、数据库
或业务工具。调用方应把同一事件分别投影到本地 AgentRun、Langfuse 和评测
采集器，避免三条链路各自拼装含义不一致的 payload。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from app.security.security import redact_secret_text

RUNTIME_EVENT_SCHEMA_VERSION = 1

ToolEffect: TypeAlias = Literal["none", "read", "write", "external"]
ToolStatus: TypeAlias = Literal[
    "requested",
    "started",
    "completed",
    "failed",
    "blocked",
    "skipped",
]
ExternalIOStatus: TypeAlias = Literal["started", "completed", "failed", "skipped"]
ApprovalStatus: TypeAlias = Literal[
    "not_required",
    "pending",
    "approved",
    "rejected",
]

_TOOL_EVENT_TYPES = frozenset(
    {
        "tool.requested",
        "tool.approval_required",
        "tool.approval_resolved",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "tool.blocked",
        "tool.skipped",
    }
)
_TOOL_EFFECTS = frozenset({"none", "read", "write", "external"})
_TOOL_STATUSES = frozenset(
    {"requested", "started", "completed", "failed", "blocked", "skipped"}
)
_EXTERNAL_IO_EVENT_TYPES = frozenset(
    {
        "external_io.started",
        "external_io.completed",
        "external_io.failed",
        "external_io.skipped",
    }
)
_EXTERNAL_IO_STATUSES = frozenset({"started", "completed", "failed", "skipped"})
_APPROVAL_EVENT_TYPES = frozenset({"approval.requested", "approval.resolved"})
_APPROVAL_STATUSES = frozenset({"not_required", "pending", "approved", "rejected"})

_TOOL_EVENT_STATUS_RULES: dict[str, frozenset[str]] = {
    "tool.requested": frozenset({"requested"}),
    "tool.approval_required": frozenset({"blocked"}),
    "tool.approval_resolved": frozenset({"started", "blocked"}),
    "tool.started": frozenset({"started"}),
    "tool.completed": frozenset({"completed"}),
    "tool.failed": frozenset({"failed"}),
    "tool.blocked": frozenset({"blocked"}),
    "tool.skipped": frozenset({"skipped"}),
}
_EXTERNAL_IO_EVENT_STATUS_RULES: dict[str, frozenset[str]] = {
    "external_io.started": frozenset({"started"}),
    "external_io.completed": frozenset({"completed"}),
    "external_io.failed": frozenset({"failed"}),
    "external_io.skipped": frozenset({"skipped"}),
}
_APPROVAL_EVENT_STATUS_RULES: dict[str, frozenset[str]] = {
    "approval.requested": frozenset({"pending"}),
    "approval.resolved": frozenset({"approved", "rejected"}),
}


def new_runtime_event_id(prefix: str) -> str:
    """生成不包含用户或业务信息的运行时事件标识。"""

    normalized = "".join(character for character in prefix.lower() if character.isalnum())
    return f"{normalized or 'evt'}_{uuid4().hex}"


def _utc_now_iso() -> str:
    """返回带时区的 UTC ISO 时间，供跨 Sink 排序和审计。"""

    return datetime.now(UTC).isoformat()


def _validate_choice(field_name: str, value: str, choices: frozenset[str]) -> None:
    """拒绝未版本化的状态值，防止聚合维度静默漂移。"""

    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{field_name} must be one of: {allowed}")


def _validate_event_status(
    event_type: str,
    status: str,
    rules: dict[str, frozenset[str]],
) -> None:
    """校验事件名称与状态组合，防止同一事件产生互相矛盾的语义。"""

    allowed = rules[event_type]
    if status not in allowed:
        expected = ", ".join(sorted(allowed))
        raise ValueError(f"{event_type} status must be one of: {expected}")


def _validate_required_text(field_name: str, value: str, *, max_length: int = 160) -> None:
    """校验事件标识和名称，避免空值或无界高基数字符串。"""

    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")


def _validate_optional_text(
    field_name: str,
    value: str | None,
    *,
    max_length: int = 256,
) -> None:
    """校验可选短文本；业务正文不得借可选字段进入观测事件。"""

    if value is not None and len(value) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")


def _validate_non_negative(field_name: str, value: int | None) -> None:
    """拒绝负数计数和耗时，避免生成不可能的评测指标。"""

    if value is not None and value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _safe_local_text(value: str | None, *, max_length: int = 300) -> str | None:
    """对仅允许进入本地审计的摘要脱敏并截断。"""

    if value is None:
        return None
    return redact_secret_text(value)[:max_length]


def _validate_short_text_collection(
    field_name: str,
    values: tuple[str, ...],
    *,
    max_items: int = 32,
    max_length: int = 120,
) -> None:
    """限制权限等本地审计维度的数量和长度，避免无界 payload。"""

    if len(values) > max_items:
        raise ValueError(f"{field_name} must contain at most {max_items} items")
    for value in values:
        _validate_required_text(field_name, value, max_length=max_length)


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """删除 None，保持事件 payload 紧凑且便于稳定比较。"""

    return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True, slots=True)
class ToolObservationEvent:
    """一次 Agent 级工具调用的状态、治理和安全审计事实。

    `to_langfuse_payload()` 永远排除参数、结果、权限列表、owner、幂等键和
    错误正文；`to_local_payload()` 才包含经过脱敏和截断的本地审计扩展。
    """

    event_type: str
    tool_name: str
    effect: ToolEffect
    status: ToolStatus
    call_id: str = field(default_factory=lambda: new_runtime_event_id("tool"))
    event_id: str = field(default_factory=lambda: new_runtime_event_id("evt"))
    trace_id: str | None = None
    agent_run_id: str | None = None
    parent_call_id: str | None = None
    agent_name: str | None = None
    workflow_name: str | None = None
    stage: str | None = None
    sequence: int | None = None
    attempt: int = 1
    duration_ms: int | None = None
    item_count: int | None = None
    result_count: int | None = None
    requires_confirmation: bool = False
    approval_status: ApprovalStatus = "not_required"
    simulated: bool = False
    degraded: bool = False
    error_type: str | None = None
    error_category: str | None = None
    required_permissions: tuple[str, ...] = ()
    granted_permissions: tuple[str, ...] = ()
    resource_owner_hash: str | None = None
    idempotency_key_hash: str | None = None
    target_namespace: str | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    error_message: str | None = None
    emitted_at: str = field(default_factory=_utc_now_iso)
    schema_version: int = RUNTIME_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """校验状态机字段和有界元数据，不执行任何外部写入。"""

        _validate_choice("event_type", self.event_type, _TOOL_EVENT_TYPES)
        _validate_choice("effect", self.effect, _TOOL_EFFECTS)
        _validate_choice("status", self.status, _TOOL_STATUSES)
        _validate_choice("approval_status", self.approval_status, _APPROVAL_STATUSES)
        _validate_event_status(self.event_type, self.status, _TOOL_EVENT_STATUS_RULES)
        _validate_required_text("tool_name", self.tool_name)
        _validate_required_text("call_id", self.call_id)
        _validate_required_text("event_id", self.event_id)
        if self.attempt < 1:
            raise ValueError("attempt must be at least 1")
        for name, value in (
            ("sequence", self.sequence),
            ("duration_ms", self.duration_ms),
            ("item_count", self.item_count),
            ("result_count", self.result_count),
        ):
            _validate_non_negative(name, value)
        for name, value in (
            ("trace_id", self.trace_id),
            ("agent_run_id", self.agent_run_id),
            ("parent_call_id", self.parent_call_id),
            ("agent_name", self.agent_name),
            ("workflow_name", self.workflow_name),
            ("stage", self.stage),
            ("error_type", self.error_type),
            ("error_category", self.error_category),
            ("resource_owner_hash", self.resource_owner_hash),
            ("idempotency_key_hash", self.idempotency_key_hash),
            ("target_namespace", self.target_namespace),
            ("emitted_at", self.emitted_at),
        ):
            _validate_optional_text(name, value)
        _validate_short_text_collection("required_permissions", self.required_permissions)
        _validate_short_text_collection("granted_permissions", self.granted_permissions)
        if self.schema_version != RUNTIME_EVENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported runtime event schema_version: {self.schema_version}"
            )

    def to_langfuse_payload(self) -> dict[str, Any]:
        """返回仅含固定短标量的 Langfuse 安全投影。"""

        return _compact_payload(
            {
                "schema_version": self.schema_version,
                "event_type": self.event_type,
                "event_id": self.event_id,
                "trace_id": self.trace_id,
                "agent_run_id": self.agent_run_id,
                "call_id": self.call_id,
                "parent_call_id": self.parent_call_id,
                "agent_name": self.agent_name,
                "workflow_name": self.workflow_name,
                "stage": self.stage,
                "sequence": self.sequence,
                "tool_name": self.tool_name,
                "tool_effect": self.effect,
                "status": self.status,
                "attempt": self.attempt,
                "duration_ms": self.duration_ms,
                "item_count": self.item_count,
                "result_count": self.result_count,
                "requires_confirmation": self.requires_confirmation,
                "approval_status": self.approval_status,
                "simulated": self.simulated,
                "degraded": self.degraded,
                "error_type": self.error_type,
                "error_category": self.error_category,
                "emitted_at": self.emitted_at,
            }
        )

    def to_local_payload(self) -> dict[str, Any]:
        """返回 AgentRun 可持久化的脱敏审计投影。"""

        payload = asdict(self)
        # `effect` 保留给现有 AgentRun/BOSS Reader；`tool_effect` 是新统一字段。
        # 所有旧 Reader 迁移完成后，再按兼容清理规则删除别名。
        payload["tool_effect"] = self.effect
        payload["input_summary"] = _safe_local_text(self.input_summary, max_length=200)
        payload["output_summary"] = _safe_local_text(self.output_summary, max_length=300)
        payload["error_message"] = _safe_local_text(self.error_message, max_length=200)
        payload["required_permissions"] = list(self.required_permissions)
        payload["granted_permissions"] = list(self.granted_permissions)
        return _compact_payload(payload)


@dataclass(frozen=True, slots=True)
class ExternalIOObservationEvent:
    """一次外部依赖调用的可用性、延迟和安全计数事实。"""

    event_type: str
    operation: str
    status: ExternalIOStatus
    call_id: str = field(default_factory=lambda: new_runtime_event_id("io"))
    event_id: str = field(default_factory=lambda: new_runtime_event_id("evt"))
    trace_id: str | None = None
    agent_run_id: str | None = None
    parent_call_id: str | None = None
    agent_name: str | None = None
    workflow_name: str | None = None
    stage: str | None = None
    dependency: str | None = None
    sequence: int | None = None
    attempt: int = 1
    duration_ms: int | None = None
    item_count: int | None = None
    result_count: int | None = None
    cache_hit: bool | None = None
    degraded: bool = False
    error_type: str | None = None
    error_category: str | None = None
    query_fingerprint: str | None = None
    emitted_at: str = field(default_factory=_utc_now_iso)
    schema_version: int = RUNTIME_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """校验依赖事件字段，禁止任意 operation 和计数扩张。"""

        _validate_choice("event_type", self.event_type, _EXTERNAL_IO_EVENT_TYPES)
        _validate_choice("status", self.status, _EXTERNAL_IO_STATUSES)
        _validate_event_status(
            self.event_type, self.status, _EXTERNAL_IO_EVENT_STATUS_RULES
        )
        _validate_required_text("operation", self.operation)
        _validate_required_text("call_id", self.call_id)
        _validate_required_text("event_id", self.event_id)
        if self.attempt < 1:
            raise ValueError("attempt must be at least 1")
        for name, value in (
            ("sequence", self.sequence),
            ("duration_ms", self.duration_ms),
            ("item_count", self.item_count),
            ("result_count", self.result_count),
        ):
            _validate_non_negative(name, value)
        for name, value in (
            ("trace_id", self.trace_id),
            ("agent_run_id", self.agent_run_id),
            ("parent_call_id", self.parent_call_id),
            ("agent_name", self.agent_name),
            ("workflow_name", self.workflow_name),
            ("stage", self.stage),
            ("dependency", self.dependency),
            ("error_type", self.error_type),
            ("error_category", self.error_category),
            ("query_fingerprint", self.query_fingerprint),
            ("emitted_at", self.emitted_at),
        ):
            _validate_optional_text(name, value)
        if self.schema_version != RUNTIME_EVENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported runtime event schema_version: {self.schema_version}"
            )

    def to_langfuse_payload(self) -> dict[str, Any]:
        """返回不含 query、文档、URL 和响应正文的安全投影。"""

        return _compact_payload(asdict(self))

    def to_local_payload(self) -> dict[str, Any]:
        """返回本地和评测可复用的结构化依赖事件。"""

        return self.to_langfuse_payload()


@dataclass(frozen=True, slots=True)
class ApprovalObservationEvent:
    """一次人工审批请求或决定的匿名化运行时事实。"""

    event_type: str
    approval_id: str
    action: str
    status: ApprovalStatus
    call_id: str | None = None
    event_id: str = field(default_factory=lambda: new_runtime_event_id("evt"))
    trace_id: str | None = None
    agent_run_id: str | None = None
    parent_call_id: str | None = None
    agent_name: str | None = None
    workflow_name: str | None = None
    stage: str | None = None
    requested_sequence: int | None = None
    decided_sequence: int | None = None
    actor_hash: str | None = None
    emitted_at: str = field(default_factory=_utc_now_iso)
    schema_version: int = RUNTIME_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """校验审批状态和序列，不保存原始用户身份。"""

        _validate_choice("event_type", self.event_type, _APPROVAL_EVENT_TYPES)
        _validate_choice("status", self.status, _APPROVAL_STATUSES)
        _validate_event_status(
            self.event_type, self.status, _APPROVAL_EVENT_STATUS_RULES
        )
        _validate_required_text("approval_id", self.approval_id)
        _validate_required_text("action", self.action)
        _validate_required_text("event_id", self.event_id)
        for name, value in (
            ("requested_sequence", self.requested_sequence),
            ("decided_sequence", self.decided_sequence),
        ):
            _validate_non_negative(name, value)
        for name, value in (
            ("call_id", self.call_id),
            ("trace_id", self.trace_id),
            ("agent_run_id", self.agent_run_id),
            ("parent_call_id", self.parent_call_id),
            ("agent_name", self.agent_name),
            ("workflow_name", self.workflow_name),
            ("stage", self.stage),
            ("actor_hash", self.actor_hash),
            ("emitted_at", self.emitted_at),
        ):
            _validate_optional_text(name, value)
        if self.schema_version != RUNTIME_EVENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported runtime event schema_version: {self.schema_version}"
            )

    def to_langfuse_payload(self) -> dict[str, Any]:
        """返回不含审批人身份的 Langfuse 安全投影。"""

        payload = asdict(self)
        payload.pop("actor_hash", None)
        return _compact_payload(payload)

    def to_local_payload(self) -> dict[str, Any]:
        """返回仅包含审批人安全哈希的本地审计投影。"""

        return _compact_payload(asdict(self))


RuntimeObservationEvent: TypeAlias = (
    ToolObservationEvent | ExternalIOObservationEvent | ApprovalObservationEvent
)
