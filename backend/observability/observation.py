"""Agent 根观测：AgentObservation 数据类与 agent_observation 生命周期。

本模块持有 Agent 根 span 的创建/嵌套复用/持久化/安全同步逻辑，以及
trace 完整性摘要等纯计算辅助函数。
"""

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from app.security.security import safe_error_message

from observability.config import _env_bool
from observability.events import (
    get_current_model_events,
    get_current_runtime_events,
)
from observability.privacy import (
    sanitize_trace_payload as _sanitize_trace_payload,
    trace_fingerprint as _trace_fingerprint,
)
from observability.runtime_events import RUNTIME_EVENT_SCHEMA_VERSION
from observability.state import (
    _active_agent_observation,
    _active_trace_id,
    _agent_name,
    _agent_run_id,
    _model_events,
    _runtime_events,
)
from observability.summaries import (
    summarize_approval_events,
    summarize_external_io_events,
    summarize_model_events,
    summarize_tool_events,
)

logger = logging.getLogger(__name__)


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


async def _persist_agent_observation(observation: "AgentObservation") -> None:
    """持久化 Agent 观测结果；失败只记录脱敏异常类型，不阻断已完成的业务流程。

    Args:
        observation: 当前观测对象；更新前会应用脱敏和失败不阻断业务的约束。
    """
    # A locally generated UUID is only an execution correlation fallback.  It is
    # not a Langfuse trace and must never make Run Center render a broken link.
    if not observation.run_id or (not observation.enabled and not observation.model_events):
        return
    try:
        import observability

        service = observability._get_agent_run_service()
        await service.record_observation(
            observation.run_id,
            observation_id=observation.trace_id,
            trace_id=observation.trace_id if observation.enabled else None,
            model_events=observation.model_events or [],
        )
    except Exception as error:
        logger.warning("AgentRun 观测持久化失败: %s", type(error).__name__)


def _get_agent_run_service() -> Any:
    """获取 AgentRun 持久化服务，用于记录观测关联状态；服务不可用时由调用方遵循不阻断业务的 fallback。"""
    from ai.runtime.agent_runs.service import AgentRunService

    return AgentRunService()


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
    import observability

    if not observability._configured:
        observability.configure_langfuse()

    parent_trace_id = _active_trace_id.get()
    if _active_agent_observation.get() and parent_trace_id:
        observation = AgentObservation(
            enabled=observability._client is not None,
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

        if observability._client is None:
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
            with observability._client.start_as_current_observation(
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
    if observability._client is not None:
        try:
            trace_id = str(observability._client.create_trace_id())
        except Exception as error:
            logger.warning("Langfuse Trace ID 创建失败，使用本地 ID: %s", type(error).__name__)

    observation = AgentObservation(
        enabled=observability._client is not None,
        input_payload=input_payload,
        trace_id=trace_id,
        run_id=run_id,
    )
    token_run_id = _agent_run_id.set(run_id)
    token_agent_name = _agent_name.set(agent_type)
    token_trace_id = _active_trace_id.set(trace_id)
    if observability._client is None:
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
        propagate_attributes = observability._get_propagate_attributes()
        metadata = {"agent_type": agent_type, "trace_id": observation.trace_id}
        if run_id:
            metadata["agent_run_id"] = _trace_fingerprint(run_id)
        with observability._client.start_as_current_observation(
            as_type="span",
            name=name,
            trace_context={"trace_id": observation.trace_id},
        ) as span:
            with propagate_attributes(
                trace_name=name,
                user_id=_trace_fingerprint(user_id) if user_id else None,
                session_id=_trace_fingerprint(session_id) if session_id else None,
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
    safe_input_payload = _sanitize_trace_payload(observation.input_payload)
    safe_observation_output = _sanitize_trace_payload(observation.output_payload or {})
    output_payload = {"trace_id": observation.trace_id, **safe_observation_output}
    if observation.run_id:
        output_payload["agent_run_id"] = _trace_fingerprint(observation.run_id)
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
        output_payload = {
            **output_payload,
            "error": _sanitize_trace_payload(observation.error_payload),
        }
    try:
        span.update(input=safe_input_payload, output=output_payload)
    except Exception as error:
        logger.warning("Langfuse span 更新失败: %s", type(error).__name__)
