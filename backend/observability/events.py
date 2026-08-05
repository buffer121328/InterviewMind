"""运行时/模型事件的记录、评测 Sink 投影与调用元数据作用域。

所有事件只携带固定审计字段，不接收用户正文、session 或业务对象 ID；
评测 Collector 通过 ContextVar 接收同一个不可变事件，Sink 失败只标记本地
observability degradation，不改变工具、检索或审批业务终态。
"""

import logging
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, cast

from observability.runtime_events import (
    ApprovalObservationEvent,
    ExternalIOObservationEvent,
    RuntimeObservationEvent,
    ToolObservationEvent,
)
from observability.state import (
    _active_agent_observation,
    _active_trace_id,
    _agent_name,
    _agent_run_id,
    _evaluation_model_sinks,
    _evaluation_runtime_sinks,
    _model_call_metadata,
    _model_events,
    _runtime_events,
    _runtime_sink_errors,
)

logger = logging.getLogger(__name__)


_SAFE_MODEL_EVENT_FIELDS = {
    "agent_name",
    "attempt",
    "cache_hit",
    "candidate_count",
    "candidate_index",
    "channel",
    "deadline_ms",
    "deadline_remaining_ms",
    "degraded",
    "duration_ms",
    "error_category",
    "error_code",
    "error_type",
    "estimated_input_tokens",
    "event_type",
    "failure_type",
    "fallback_index",
    "first_chunk_duration_ms",
    "input_chars",
    "input_fingerprint",
    "input_tokens",
    "item_count",
    "max_retries",
    "model_duration_ms",
    "model_member",
    "model_name",
    "model_provider",
    "model_integration",
    "model_endpoint",
    "pricing_key",
    "usage_status",
    "total_tokens",
    "cache_read_tokens",
    "reasoning_tokens",
    "estimated_cost_cny",
    "estimated_cost_usd",
    "cost_currency",
    "cost_source",
    "cost_status",
    "operation",
    "output_token_limit",
    "output_tokens",
    "prompt_label",
    "prompt_name",
    "prompt_source",
    "prompt_version",
    "queue_wait_ms",
    "result_count",
    "source_breakdown",
    "stage",
    "status",
    "total_duration_ms",
    "trace_id",
    "truncated_sources",
    "authoritative_source_truncated",
    "overflow_strategy",
    "timeout_scope",
}


def _safe_model_event_value(value: Any) -> Any:
    """把事件值限制为短标量或计数映射，拒绝任意业务 payload。"""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:160]
    if isinstance(value, Mapping):
        safe_mapping: dict[str, int | float | bool | None] = {}
        for key, item in value.items():
            if isinstance(item, (int, float, bool)) or item is None:
                safe_mapping[str(key)[:64]] = item
        return safe_mapping
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item)[:64] for item in value[:32]]
    return None


def record_model_event(**event: Any) -> None:
    """记录模型与外部 AI 服务事件，只接受无原文的固定审计字段。

    Args:
        **event: 事件对象。
    """
    events = _model_events.get()
    sinks = tuple(_evaluation_model_sinks.get() or ())
    if events is None and not sinks:
        return
    enriched_event = {
        "agent_name": _agent_name.get(),
        "trace_id": _active_trace_id.get(),
        **event,
    }
    safe_event = {
        key: safe_value
        for key, value in enriched_event.items()
        if key in _SAFE_MODEL_EVENT_FIELDS
        and (safe_value := _safe_model_event_value(value)) is not None
    }
    if events is not None:
        events.append(safe_event)
    for sink in sinks:
        try:
            sink(dict(safe_event))
        except Exception as exc:  # noqa: BLE001 - 评测观测不得阻断模型调用。
            errors = _runtime_sink_errors.get()
            if errors is not None:
                errors.append(type(exc).__name__)
            logger.warning("评测 Model Sink 写入失败: %s", type(exc).__name__)


def bind_runtime_event_context(
    event: RuntimeObservationEvent,
) -> RuntimeObservationEvent:
    """把当前 Trace、AgentRun 和 Agent 身份补充到不可变运行时事件。

    已由调用方显式提供的关联字段优先保留；本函数只补空值，不读取用户正文、
    session 或业务对象 ID。
    """

    updates: dict[str, Any] = {}
    if event.trace_id is None:
        updates["trace_id"] = _active_trace_id.get()
    if event.agent_run_id is None:
        updates["agent_run_id"] = _agent_run_id.get()
    if event.agent_name is None:
        updates["agent_name"] = _agent_name.get()
    return replace(event, **updates) if updates else event


def record_runtime_event(
    event: RuntimeObservationEvent,
) -> RuntimeObservationEvent:
    """记录统一运行时事件并投影到所有启用的 Sink。

    事件只以 ``to_langfuse_payload()`` 的固定字段进入 Langfuse 根观测；评测
    Collector 通过 ContextVar 接收同一个不可变事件，Sink 失败只标记本地
    observability degradation，不改变工具、检索或审批业务终态。
    """

    bound_event = bind_runtime_event_context(event)
    events = _runtime_events.get()
    if events is not None:
        events.append(bound_event.to_langfuse_payload())
    for sink in tuple(_evaluation_runtime_sinks.get() or ()):
        try:
            sink(bound_event)
        except Exception as exc:  # noqa: BLE001 - 观测 Sink 不得阻断业务。
            errors = _runtime_sink_errors.get()
            if errors is not None:
                errors.append(type(exc).__name__)
            logger.warning("运行时观测 Sink 失败: %s", type(exc).__name__)
    if isinstance(bound_event, ToolObservationEvent):
        from observability.tool_tracing import observe_tool_event

        observe_tool_event(bound_event)
    elif isinstance(bound_event, ExternalIOObservationEvent):
        from observability.io_tracing import observe_external_io_event

        observe_external_io_event(bound_event)
    return bound_event


def record_tool_event(event: ToolObservationEvent) -> ToolObservationEvent:
    """记录 Tool 事件，不接收工具参数或结果正文的 Langfuse 投影。"""

    return cast(ToolObservationEvent, record_runtime_event(event))


def record_external_io_event(
    event: ExternalIOObservationEvent,
) -> ExternalIOObservationEvent:
    """记录 external IO 事件，不接收 query、文档、页面或 URL 正文。"""

    return cast(ExternalIOObservationEvent, record_runtime_event(event))


def record_approval_event(
    event: ApprovalObservationEvent,
) -> ApprovalObservationEvent:
    """记录匿名化审批事件；Langfuse 投影会排除 actor hash。"""

    return cast(ApprovalObservationEvent, record_runtime_event(event))


def get_current_runtime_events() -> list[dict[str, Any]]:
    """返回当前 Agent 观测中的安全运行时事件副本。"""

    events = _runtime_events.get()
    return list(events or [])


def get_current_model_events() -> list[dict[str, Any]]:
    """读取当前运行上下文中的 model events；只返回本次请求可见的状态，不修改共享配置。"""
    events = _model_events.get()
    return list(events or [])


def get_current_trace_id() -> str | None:
    """返回当前根 Trace ID，供统一事件关联本地 AgentRun 审计。"""

    return _active_trace_id.get()


def is_agent_observation_active() -> bool:
    """返回当前任务是否位于 Agent root observation 内。"""

    return _active_agent_observation.get()


@contextmanager
def evaluation_runtime_sink(sink: Any):
    """把统一运行时事件绑定到一次评测 Collector。

    该上下文只增加观测投影，不改变生产工具权限、审批或外部 IO 策略。
    """

    sinks = list(_evaluation_runtime_sinks.get() or [])
    sinks.append(sink)
    token_sinks = _evaluation_runtime_sinks.set(sinks)
    token_errors = _runtime_sink_errors.set([])
    try:
        yield
    finally:
        _evaluation_runtime_sinks.reset(token_sinks)
        _runtime_sink_errors.reset(token_errors)


@contextmanager
def evaluation_model_sink(sink: Any):
    """把脱敏模型事件绑定到一次评测 Collector，不改变模型路由或重试。"""

    sinks = list(_evaluation_model_sinks.get() or [])
    sinks.append(sink)
    token_sinks = _evaluation_model_sinks.set(sinks)
    try:
        yield
    finally:
        _evaluation_model_sinks.reset(token_sinks)


def get_runtime_sink_errors() -> tuple[str, ...]:
    """返回当前评测上下文发现的 Sink 异常类型。"""

    return tuple(_runtime_sink_errors.get() or ())


@contextmanager
def model_call_metadata_scope(**metadata: Any):
    """在一次模型 attempt 内传播候选、deadline 和上下文审计元数据。"""
    current = dict(_model_call_metadata.get() or {})
    token = _model_call_metadata.set({**current, **metadata})
    try:
        yield
    finally:
        _model_call_metadata.reset(token)


def get_current_model_call_metadata() -> dict[str, Any]:
    """返回当前 attempt 的安全观测元数据副本。"""
    return dict(_model_call_metadata.get() or {})


def filter_model_call_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """只保留调用方可覆盖的上下文审计字段，防止覆盖候选和 deadline 决策字段。"""
    allowed = {
        "input_fingerprint",
        "output_token_limit",
        "queue_wait_ms",
        "source_breakdown",
        "stage",
        "truncated_sources",
    "authoritative_source_truncated",
    "overflow_strategy",
    "timeout_scope",
    }
    return {key: value for key, value in dict(metadata or {}).items() if key in allowed}
