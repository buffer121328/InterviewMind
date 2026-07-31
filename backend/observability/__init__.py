"""Agent 的可选 Langfuse 观测适配层。"""

import logging
import uuid
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator, Optional, cast
from urllib.parse import urlsplit

from app.security.security import safe_error_message

from observability.config import LangfuseConfig, _env_bool
from observability.langfuse_client import (
    _create_langfuse_client,
    _get_callback_handler,
    _get_propagate_attributes,
)
from observability.providers import (
    estimate_model_cost,
    infer_model_integration,
    infer_model_provider,
    provider_observability_metadata,
)
from observability.summaries import (
    compare_governance_windows,
    summarize_approval_events,
    summarize_external_io_events,
    summarize_governance_window,
    summarize_model_events,
    summarize_tool_events,
)
from observability.usage import extract_token_usage, measure_model_input

from observability.runtime_events import (
    ApprovalObservationEvent,
    ExternalIOObservationEvent,
    RUNTIME_EVENT_SCHEMA_VERSION,
    RuntimeObservationEvent,
    ToolObservationEvent,
)

logger = logging.getLogger(__name__)
_active_agent_observation: ContextVar[bool] = ContextVar(
    "active_agent_observation", default=False
)
_active_trace_id: ContextVar[str | None] = ContextVar(
    "active_trace_id", default=None
)
_model_events: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "model_events", default=None
)
_runtime_events: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "runtime_events", default=None
)
_agent_run_id: ContextVar[str | None] = ContextVar(
    "agent_run_id", default=None
)
_agent_name: ContextVar[str | None] = ContextVar(
    "agent_name", default=None
)
_suppress_direct_llm_callbacks: ContextVar[bool] = ContextVar(
    "suppress_direct_llm_callbacks", default=False
)
_model_call_metadata: ContextVar[dict[str, Any] | None] = ContextVar(
    "model_call_metadata", default=None
)
_evaluation_runtime_sinks: ContextVar[list[Any] | None] = ContextVar(
    "evaluation_runtime_sinks", default=None
)
_evaluation_model_sinks: ContextVar[list[Any] | None] = ContextVar(
    "evaluation_model_sinks", default=None
)
_runtime_sink_errors: ContextVar[list[str] | None] = ContextVar(
    "runtime_sink_errors", default=None
)
_client: Any = None
_config: "LangfuseConfig | None" = None
_configured = False


@dataclass
class AgentObservation:
    """仅保存可安全上传的 Agent 输入输出摘要。"""

    enabled: bool
    input_payload: dict[str, Any]
    trace_id: str
    run_id: str | None = None
    output_payload: Optional[dict[str, Any]] = None
    error_payload: Optional[dict[str, str]] = None
    model_events: list[dict[str, Any]] | None = None
    runtime_events: list[dict[str, Any]] | None = None

    def set_output(self, output_payload: dict[str, Any]) -> None:
        """更新当前观测或流程状态中的 output；遵循调用方的数据脱敏和生命周期边界。

        Args:
            output_payload: output 载荷。
        """
        self.output_payload = output_payload

    def set_error(self, error: Exception) -> None:
        """更新当前观测或流程状态中的 error；遵循调用方的数据脱敏和生命周期边界。

        Args:
            error: 对外或日志使用的错误语义；必须保持脱敏，不包含凭据和完整输入。
        """
        self.error_payload = {
            "type": type(error).__name__,
            "message": safe_error_message(error, max_len=160),
        }





















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
    }
    return {key: value for key, value in dict(metadata or {}).items() if key in allowed}


async def _persist_agent_observation(observation: "AgentObservation") -> None:
    """持久化 Agent 观测结果；失败只记录脱敏异常类型，不阻断已完成的业务流程。

    Args:
        observation: 当前观测对象；更新前会应用脱敏和失败不阻断业务的约束。
    """
    # A locally generated UUID is only an execution correlation fallback.  It is
    # not a Langfuse trace and must never make Run Center render a broken link.
    if not observation.enabled or not observation.run_id:
        return
    try:
        service = _get_agent_run_service()
        await service.record_observation(
            observation.run_id,
            trace_id=observation.trace_id,
        )
    except Exception as error:
        logger.warning("AgentRun 观测持久化失败: %s", type(error).__name__)


def get_current_model_events() -> list[dict[str, Any]]:
    """读取当前运行上下文中的 model events；只返回本次请求可见的状态，不修改共享配置。"""
    events = _model_events.get()
    return list(events or [])










def _get_agent_run_service() -> Any:
    """获取 AgentRun 持久化服务，用于记录观测关联状态；服务不可用时由调用方遵循不阻断业务的 fallback。"""
    from ai.runtime.agent_runs.service import AgentRunService

    return AgentRunService()






def configure_langfuse() -> bool:
    """按环境变量初始化 Langfuse，失败时降级为 no-op。"""
    global _client, _config, _configured

    if _configured:
        return _client is not None

    _configured = True
    config = LangfuseConfig.from_env()
    _config = config
    if not config.enabled:
        return False
    if not config.public_key or not config.secret_key:
        logger.warning("Langfuse 已启用但缺少凭据，观测已降级为 no-op")
        return False

    try:
        _client = _create_langfuse_client(config)
    except Exception as error:
        logger.warning("Langfuse 初始化失败，观测已降级为 no-op: %s", type(error).__name__)
        _client = None
    return _client is not None


@asynccontextmanager
async def agent_observation(
    *,
    name: str,
    agent_type: str,
    user_id: Optional[str],
    session_id: Optional[str],
    input_payload: dict[str, Any],
    run_id: Optional[str] = None,
) -> AsyncIterator[AgentObservation]:
    """创建 Agent 根 span；嵌套工作流复用当前 trace 并创建子 span。"""
    if not _configured:
        configure_langfuse()

    parent_trace_id = _active_trace_id.get()
    if _active_agent_observation.get() and parent_trace_id:
        observation = AgentObservation(
            enabled=_client is not None,
            input_payload=input_payload,
            trace_id=parent_trace_id,
            run_id=run_id,
        )
        token_run_id = _agent_run_id.set(run_id or _agent_run_id.get())
        token_agent_name = _agent_name.set(agent_type)
        parent_events = _model_events.get()
        event_start = len(parent_events or [])
        parent_runtime_events = _runtime_events.get()
        runtime_event_start = len(parent_runtime_events or [])

        if _client is None:
            try:
                yield observation
            except Exception as error:
                observation.set_error(error)
                raise
            finally:
                observation.model_events = list((_model_events.get() or [])[event_start:])
                observation.runtime_events = list(
                    (_runtime_events.get() or [])[runtime_event_start:]
                )
                _agent_run_id.reset(token_run_id)
                _agent_name.reset(token_agent_name)
            return

        entered = False
        business_error = False
        try:
            with _client.start_as_current_observation(
                as_type="span",
                name=name,
            ) as span:
                entered = True
                try:
                    yield observation
                except Exception as error:
                    business_error = True
                    observation.set_error(error)
                    raise
                finally:
                    observation.model_events = list((_model_events.get() or [])[event_start:])
                    observation.runtime_events = list(
                        (_runtime_events.get() or [])[runtime_event_start:]
                    )
                    _update_span(span, observation)
        except Exception as error:
            if business_error:
                raise
            logger.warning("Langfuse 子观测失败，业务继续执行: %s", type(error).__name__)
            if not entered:
                try:
                    yield observation
                except Exception as business_exception:
                    observation.set_error(business_exception)
                    raise
                finally:
                    observation.model_events = list((_model_events.get() or [])[event_start:])
                    observation.runtime_events = list(
                        (_runtime_events.get() or [])[runtime_event_start:]
                    )
        finally:
            _agent_run_id.reset(token_run_id)
            _agent_name.reset(token_agent_name)
        return

    trace_id = str(uuid.uuid4())
    if _client is not None:
        try:
            trace_id = str(_client.create_trace_id())
        except Exception as error:
            logger.warning("Langfuse Trace ID 创建失败，使用本地 ID: %s", type(error).__name__)

    observation = AgentObservation(
        enabled=_client is not None,
        input_payload=input_payload,
        trace_id=trace_id,
        run_id=run_id,
    )
    token_run_id = _agent_run_id.set(run_id)
    token_agent_name = _agent_name.set(agent_type)
    token_trace_id = _active_trace_id.set(trace_id)
    if _client is None:
        token_active = _active_agent_observation.set(True)
        token_events = _model_events.set([])
        token_runtime_events = _runtime_events.set([])
        try:
            yield observation
        except Exception as error:
            observation.set_error(error)
            raise
        finally:
            observation.model_events = get_current_model_events()
            observation.runtime_events = get_current_runtime_events()
            await _persist_agent_observation(observation)
            _runtime_events.reset(token_runtime_events)
            _model_events.reset(token_events)
            _active_agent_observation.reset(token_active)
            _agent_run_id.reset(token_run_id)
            _agent_name.reset(token_agent_name)
            _active_trace_id.reset(token_trace_id)
        return

    entered = False
    business_error = False
    try:
        propagate_attributes = _get_propagate_attributes()
        metadata = {"agent_type": agent_type, "trace_id": observation.trace_id}
        if run_id:
            metadata["agent_run_id"] = run_id
        with _client.start_as_current_observation(
            as_type="span",
            name=name,
            trace_context={"trace_id": observation.trace_id},
        ) as span:
            with propagate_attributes(
                trace_name=name,
                user_id=user_id,
                session_id=session_id,
                metadata=metadata,
            ):
                entered = True
                token = _active_agent_observation.set(True)
                token_events = _model_events.set([])
                token_runtime_events = _runtime_events.set([])
                try:
                    yield observation
                except Exception as error:
                    business_error = True
                    observation.set_error(error)
                    raise
                finally:
                    observation.model_events = get_current_model_events()
                    observation.runtime_events = get_current_runtime_events()
                    await _persist_agent_observation(observation)
                    _runtime_events.reset(token_runtime_events)
                    _model_events.reset(token_events)
                    _active_agent_observation.reset(token)
                    _agent_run_id.reset(token_run_id)
                    _agent_name.reset(token_agent_name)
                    _active_trace_id.reset(token_trace_id)
                    _update_span(span, observation)
    except Exception as error:
        if business_error:
            raise
        logger.warning("Langfuse 观测失败，业务继续执行: %s", type(error).__name__)
        if not entered:
            fallback = AgentObservation(
                enabled=False,
                input_payload=input_payload,
                trace_id=observation.trace_id,
                run_id=run_id,
            )
            token_events = _model_events.set([])
            token_runtime_events = _runtime_events.set([])
            try:
                yield fallback
            finally:
                fallback.model_events = get_current_model_events()
                fallback.runtime_events = get_current_runtime_events()
                await _persist_agent_observation(fallback)
                _runtime_events.reset(token_runtime_events)
                _model_events.reset(token_events)
                _agent_run_id.reset(token_run_id)
                _agent_name.reset(token_agent_name)
                _active_trace_id.reset(token_trace_id)


def _trace_completeness_summary(observation: AgentObservation) -> dict[str, Any]:
    """从安全事件和根元数据生成 critical trace 完整性摘要。"""

    events = observation.runtime_events or []
    tools = [
        event for event in events
        if str(event.get("event_type") or "").startswith("tool.")
    ]
    calls = {str(event.get("call_id")) for event in tools if event.get("call_id")}
    terminal_statuses = {"completed", "failed", "blocked", "skipped"}
    terminal_calls = {
        str(event.get("call_id"))
        for event in tools
        if event.get("call_id") and event.get("status") in terminal_statuses
    }
    tool_terminal_states_complete = calls.issubset(terminal_calls)
    stable_error_categories = all(
        event.get("status") != "failed" or bool(event.get("error_category"))
        for event in tools
    )
    external_approval_status_present = all(
        event.get("tool_effect") != "external" or bool(event.get("approval_status"))
        for event in tools
    )
    model_events = observation.model_events or []
    prompt_version_present = bool(observation.input_payload.get("prompt_version")) or not bool(
        observation.input_payload.get("prompt_name")
    )
    model_config_hash_present = bool(observation.input_payload.get("model_config_hash")) or any(
        event.get("model_name") or event.get("model_member") for event in model_events
    )
    checks = {
        "trace_id": bool(observation.trace_id),
        "agent_version": bool(observation.input_payload.get("agent_version")),
        "prompt_version": prompt_version_present,
        "model_config_hash": model_config_hash_present,
        "tool_terminal_states": tool_terminal_states_complete,
        "stable_error_categories": stable_error_categories,
        "external_approval_status": external_approval_status_present,
        "agent_run_id": bool(observation.run_id),
    }
    missing = tuple(name for name, passed in checks.items() if not passed)
    return {
        "complete": not missing,
        "score": sum(checks.values()) / len(checks),
        "missing": missing,
        "trace_id_present": bool(observation.trace_id),
        "agent_version_present": bool(observation.input_payload.get("agent_version")),
        "prompt_version_present": prompt_version_present,
        "model_config_hash_present": model_config_hash_present,
        "tool_terminal_states_complete": tool_terminal_states_complete,
        "stable_error_categories": stable_error_categories,
        "external_approval_status_present": external_approval_status_present,
        "agent_run_id_present": bool(observation.run_id),
    }


def _update_span(span: Any, observation: AgentObservation) -> None:
    """把观测结果安全地同步到 span；先应用脱敏和字段长度限制，外部追踪失败只记录本地日志。

    Args:
        span: 当前观测对象；更新前会应用脱敏和失败不阻断业务的约束。
        observation: 当前观测对象；更新前会应用脱敏和失败不阻断业务的约束。
    """
    output_payload = {"trace_id": observation.trace_id, **(observation.output_payload or {})}
    if observation.run_id:
        output_payload["agent_run_id"] = observation.run_id
    if observation.model_events:
        output_payload["model_event_count"] = len(observation.model_events)
        output_payload["model_event_summary"] = summarize_model_events(observation.model_events)
        if _env_bool("LANGFUSE_INCLUDE_MODEL_EVENTS_IN_SPAN_OUTPUT", False):
            output_payload["model_events"] = observation.model_events
    if observation.runtime_events:
        output_payload["observability_schema_version"] = RUNTIME_EVENT_SCHEMA_VERSION
        output_payload["runtime_event_count"] = len(observation.runtime_events)
        output_payload["tool_event_count"] = sum(
            str(event.get("event_type") or "").startswith("tool.")
            for event in observation.runtime_events
        )
        output_payload["external_io_event_count"] = sum(
            str(event.get("event_type") or "").startswith("external_io.")
            for event in observation.runtime_events
        )
        output_payload["approval_event_count"] = sum(
            str(event.get("event_type") or "").startswith("approval.")
            for event in observation.runtime_events
        )
        output_payload["tool_call_summary"] = summarize_tool_events(
            observation.runtime_events
        )
        output_payload["trace_completeness"] = _trace_completeness_summary(observation)
        output_payload["external_io_summary"] = summarize_external_io_events(
            observation.runtime_events
        )
        output_payload["approval_event_summary"] = summarize_approval_events(
            observation.runtime_events
        )
    if observation.error_payload:
        output_payload = {**output_payload, "error": observation.error_payload}
    try:
        span.update(input=observation.input_payload, output=output_payload)
    except Exception as error:
        logger.warning("Langfuse span 更新失败: %s", type(error).__name__)


def _create_callback_handler_instance() -> Any | None:
    """创建 Langfuse 官方 LangChain/LangGraph callback handler。"""
    if _client is None:
        return None
    try:
        return _get_callback_handler()()
    except Exception as error:
        logger.warning("Langfuse CallbackHandler 创建失败: %s", type(error).__name__)
        return None


def get_langchain_callbacks() -> list[Any]:
    """为直接 LangChain 模型绑定回调，并在缺少根 span 时创建独立 trace。

    当 LangGraph run 级 callback 已启用时，LangGraph 会通过 config 将
    callback 传播给节点/模型调用。此时抑制直接挂在 ChatOpenAI 上的
    callback，避免同一次 LLM 调用在 Langfuse 中重复上报。
    """
    if not _configured:
        configure_langfuse()
    if _client is None or _suppress_direct_llm_callbacks.get():
        return []
    handler = _create_callback_handler_instance()
    return [handler] if handler is not None else []


def get_langgraph_callbacks() -> list[Any]:
    """返回 Langfuse 官方 LangGraph callback handler。

    Langfuse 官方通过 `langfuse.langchain.CallbackHandler` 接入 LangGraph：
    在 `graph.invoke/ainvoke/stream/astream_events` 的 config 里传入
    `callbacks`，LangGraph 会生成图与节点级 run，并将 callback 传播到
    子 runnable。该回调可在 Agent 根 span 内工作，也可为独立 Graph
    调用创建自己的 Langfuse trace。
    """
    if not _configured:
        configure_langfuse()
    handler = _create_callback_handler_instance()
    return [handler] if handler is not None else []


def with_langgraph_langfuse_config(
    config: dict[str, Any] | None = None,
    *,
    run_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把 Langfuse LangGraph callback 合并进 LangGraph 调用 config。

    保留原有 `configurable.thread_id` 等配置，并追加 `callbacks`、
    `run_name` 和 `metadata`。未启用 Langfuse 时原样返回配置副本。
    """
    merged: dict[str, Any] = dict(config or {})
    callbacks = list(merged.get("callbacks") or [])
    callbacks.extend(get_langgraph_callbacks())
    if callbacks:
        merged["callbacks"] = callbacks
    if run_name and "run_name" not in merged:
        merged["run_name"] = run_name
    if metadata:
        merged["metadata"] = {**dict(merged.get("metadata") or {}), **metadata}
    return merged




@contextmanager
def langgraph_langfuse_scope(enabled: bool = True):
    """在 LangGraph run 级 callback 生效期间抑制直接 LLM callback。"""
    token = _suppress_direct_llm_callbacks.set(bool(enabled))
    try:
        yield
    finally:
        _suppress_direct_llm_callbacks.reset(token)






def get_langfuse_client() -> Any | None:
    """Return the configured Langfuse client, initializing it from env if needed."""
    if not _configured:
        configure_langfuse()
    return _client


def get_langfuse_trace_url(trace_id: str) -> str | None:
    """返回已配置项目中的 Trace URL，不向前端暴露 Langfuse 凭据。"""
    normalized_trace_id = trace_id.strip()
    if not normalized_trace_id:
        return None

    client = get_langfuse_client()
    if client is None:
        return None
    try:
        url = client.get_trace_url(trace_id=normalized_trace_id)
    except Exception as error:
        logger.warning("Langfuse Trace URL 获取失败: %s", type(error).__name__)
        return None

    if not isinstance(url, str) or len(url) > 2048:
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        logger.warning("Langfuse 返回了无效的 Trace URL")
        return None
    return url


def _current_config() -> LangfuseConfig:
    """Return the cached Langfuse config, loading it lazily when needed."""
    global _config
    if _config is None:
        _config = LangfuseConfig.from_env()
    return _config


def render_managed_prompt(
    *,
    name: str,
    fallback: str,
    values: dict[str, Any],
    version: str | int | None = None,
    prompt_type: str = "text",
) -> str:
    """Render a Langfuse-managed prompt with a local fallback.

    Prompt management is opt-in via LANGFUSE_PROMPT_MANAGEMENT_ENABLED=true.
    When disabled, unavailable, or failing, this returns the already-rendered local
    fallback so production traffic is not coupled to Langfuse availability.
    """
    if not _configured:
        configure_langfuse()
    config = _current_config()
    if _client is None or not config.prompt_management_enabled:
        return fallback

    prompt_kwargs: dict[str, Any] = {
        "type": prompt_type,
        "cache_ttl_seconds": config.prompt_cache_ttl_seconds,
        "fallback": fallback,
    }
    if config.prompt_label:
        prompt_kwargs["label"] = config.prompt_label
    else:
        try:
            if version is not None:
                prompt_kwargs["version"] = int(version)
        except (TypeError, ValueError):
            pass

    try:
        prompt_client = _client.get_prompt(name, **prompt_kwargs)
        rendered = prompt_client.compile(**values)
        if isinstance(rendered, list):
            rendered_text = "\n".join(
                str(item.get("content", item)) if isinstance(item, dict) else str(item)
                for item in rendered
            )
        else:
            rendered_text = str(rendered)
        record_model_event(
            event_type="prompt.rendered",
            prompt_name=name,
            prompt_version=str(version) if version is not None else None,
            prompt_label=config.prompt_label,
            prompt_source=(
                "langfuse"
                if not getattr(prompt_client, "is_fallback", False)
                else "fallback"
            ),
        )
        return rendered_text
    except Exception as error:
        logger.warning("Langfuse prompt 获取失败，使用本地 Prompt: %s", type(error).__name__)
        record_model_event(
            event_type="prompt.rendered",
            prompt_name=name,
            prompt_version=str(version) if version is not None else None,
            prompt_label=config.prompt_label,
            prompt_source="fallback",
        )
        return fallback


def record_score(
    *,
    name: str,
    value: float | str | bool,
    trace_id: str | None = None,
    observation_id: str | None = None,
    session_id: str | None = None,
    dataset_run_id: str | None = None,
    score_id: str | None = None,
    data_type: str | None = None,
    comment: str | None = None,
    config_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    environment: str | None = None,
) -> bool:
    """Attach an evaluation score to Langfuse.

    Supports the Langfuse score targets used by traces, observations, sessions
    and dataset runs. When no explicit target is supplied, the current trace
    context is scored. SDK failures are swallowed so evaluations never break
    business logic or CI.
    """
    if not _configured:
        configure_langfuse()
    if _client is None:
        return False

    payload = {
        "name": name,
        "value": value,
        "trace_id": trace_id,
        "observation_id": observation_id,
        "session_id": session_id,
        "dataset_run_id": dataset_run_id,
        "score_id": score_id,
        "data_type": data_type,
        "comment": comment,
        "config_id": config_id,
        "metadata": metadata,
        "environment": environment or _current_config().environment,
    }
    compact_payload = {key: item for key, item in payload.items() if item is not None}

    try:
        if trace_id or observation_id or session_id or dataset_run_id:
            _client.create_score(**compact_payload)
        else:
            _client.score_current_trace(
                name=name,
                value=value,
                data_type=data_type,
                comment=comment,
                config_id=config_id,
                metadata=metadata,
            )
        return True
    except Exception as error:
        logger.warning("Langfuse score 写入失败: %s", type(error).__name__)
        return False


def record_trace_score(
    *,
    name: str,
    value: float | str | bool,
    trace_id: str | None = None,
    comment: str | None = None,
    data_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Record a trace-level score."""
    return record_score(
        name=name,
        value=value,
        trace_id=trace_id,
        comment=comment,
        data_type=data_type,
        metadata=metadata,
    )


def shutdown_langfuse() -> None:
    """关闭客户端并尽量刷新异步上报缓冲。"""
    global _client, _config, _configured

    client, _client = _client, None
    _config = None
    _configured = False
    if client is None:
        return
    try:
        client.shutdown()
    except Exception as error:
        logger.warning("Langfuse 关闭失败: %s", type(error).__name__)



def _reset_langfuse_for_tests() -> None:
    """重置 Langfuse 模块状态，供离线单元测试隔离使用。"""
    global _client, _config, _configured

    _client = None
    _config = None
    _configured = False
    _active_agent_observation.set(False)
    _active_trace_id.set(None)
    _model_events.set(None)
    _runtime_events.set(None)
    _agent_run_id.set(None)
    _agent_name.set(None)
    _suppress_direct_llm_callbacks.set(False)
    _model_call_metadata.set(None)
    _evaluation_runtime_sinks.set(None)
    _evaluation_model_sinks.set(None)
    _runtime_sink_errors.set(None)
    from observability.tool_tracing import reset_tool_spans

    reset_tool_spans()
