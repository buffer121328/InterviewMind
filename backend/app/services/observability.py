"""Agent 的可选 Langfuse 观测适配层。"""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional


logger = logging.getLogger(__name__)
_active_agent_observation: ContextVar[bool] = ContextVar(
    "active_agent_observation", default=False
)
_model_events: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "model_events", default=None
)
_agent_run_id: ContextVar[str | None] = ContextVar(
    "agent_run_id", default=None
)
_client: Any = None
_configured = False


@dataclass(frozen=True)
class LangfuseConfig:
    enabled: bool
    public_key: str = ""
    secret_key: str = ""
    base_url: str = "https://cloud.langfuse.com"

    @classmethod
    def from_env(cls) -> "LangfuseConfig":
        enabled = os.getenv("LANGFUSE_ENABLED", "false").lower() in {"1", "true", "yes"}
        return cls(
            enabled=enabled,
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            base_url=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        )


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

    def set_output(self, output_payload: dict[str, Any]) -> None:
        self.output_payload = output_payload

    def set_error(self, error: Exception) -> None:
        self.error_payload = {
            "type": type(error).__name__,
            "message": str(error)[:160],
        }




def extract_token_usage(value: Any) -> dict[str, int | None]:
    """尽量从 LangChain/OpenAI 响应对象中提取 token usage。"""
    usage = getattr(value, "usage_metadata", None)
    if isinstance(usage, dict):
        return {
            "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens"),
            "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens"),
        }
    response_metadata = getattr(value, "response_metadata", None)
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
        if isinstance(token_usage, dict):
            return {
                "input_tokens": token_usage.get("prompt_tokens") or token_usage.get("input_tokens"),
                "output_tokens": token_usage.get("completion_tokens") or token_usage.get("output_tokens"),
            }
    raw_usage = getattr(value, "usage", None)
    if raw_usage is not None:
        return {
            "input_tokens": getattr(raw_usage, "prompt_tokens", None) or getattr(raw_usage, "input_tokens", None),
            "output_tokens": getattr(raw_usage, "completion_tokens", None) or getattr(raw_usage, "output_tokens", None),
        }
    return {"input_tokens": None, "output_tokens": None}


def record_model_event(**event: Any) -> None:
    events = _model_events.get()
    if events is None:
        return
    safe_event = dict(event)
    safe_event.pop("api_key", None)
    events.append(safe_event)


async def _persist_agent_observation(observation: "AgentObservation") -> None:
    if not observation.run_id:
        return
    try:
        service = _get_agent_run_service()
        await service.record_observation(
            observation.run_id,
            trace_id=observation.trace_id,
            model_events=list(observation.model_events or []),
        )
    except Exception as error:
        logger.warning("AgentRun 观测持久化失败: %s", type(error).__name__)


def get_current_model_events() -> list[dict[str, Any]]:
    events = _model_events.get()
    return list(events or [])

def _create_langfuse_client(config: LangfuseConfig) -> Any:
    from langfuse import Langfuse

    return Langfuse(
        public_key=config.public_key,
        secret_key=config.secret_key,
        base_url=config.base_url,
    )


def _get_agent_run_service() -> Any:
    from app.services.agent_runs.service import AgentRunService

    return AgentRunService()


def _get_propagate_attributes():
    from langfuse import propagate_attributes

    return propagate_attributes


def _get_callback_handler():
    try:
        from langfuse.langchain import CallbackHandler
    except ModuleNotFoundError:
        class CallbackHandler:  # pragma: no cover - 轻量测试环境占位
            def __call__(self, *args: Any, **kwargs: Any) -> None:
                return None

        return CallbackHandler

    return CallbackHandler


def configure_observability() -> bool:
    """按环境变量初始化 Langfuse，失败时降级为 no-op。"""
    global _client, _configured

    if _configured:
        return _client is not None

    _configured = True
    config = LangfuseConfig.from_env()
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
    """为一次 Agent 执行创建根 span，SDK 故障不影响业务链路。"""
    if not _configured:
        configure_observability()

    observation = AgentObservation(
        enabled=_client is not None,
        input_payload=input_payload,
        trace_id=str(uuid.uuid4()),
        run_id=run_id,
    )
    token_run_id = _agent_run_id.set(run_id)
    if _client is None:
        token_events = _model_events.set([])
        try:
            yield observation
        finally:
            observation.model_events = get_current_model_events()
            await _persist_agent_observation(observation)
            _model_events.reset(token_events)
            _agent_run_id.reset(token_run_id)
        return

    entered = False
    business_error = False
    try:
        propagate_attributes = _get_propagate_attributes()
        metadata = {"agent_type": agent_type, "trace_id": observation.trace_id}
        if run_id:
            metadata["agent_run_id"] = run_id
        with _client.start_as_current_observation(as_type="span", name=name) as span:
            with propagate_attributes(
                trace_name=name,
                user_id=user_id,
                session_id=session_id,
                metadata=metadata,
            ):
                entered = True
                token = _active_agent_observation.set(True)
                token_events = _model_events.set([])
                try:
                    yield observation
                except Exception as error:
                    business_error = True
                    observation.set_error(error)
                    raise
                finally:
                    observation.model_events = get_current_model_events()
                    await _persist_agent_observation(observation)
                    _model_events.reset(token_events)
                    _active_agent_observation.reset(token)
                    _agent_run_id.reset(token_run_id)
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
            try:
                yield fallback
            finally:
                fallback.model_events = get_current_model_events()
                await _persist_agent_observation(fallback)
                _model_events.reset(token_events)
                _agent_run_id.reset(token_run_id)


def _update_span(span: Any, observation: AgentObservation) -> None:
    output_payload = {"trace_id": observation.trace_id, **(observation.output_payload or {})}
    if observation.run_id:
        output_payload["agent_run_id"] = observation.run_id
    if observation.model_events:
        output_payload["model_events"] = observation.model_events
    if observation.error_payload:
        output_payload = {**output_payload, "error": observation.error_payload}
    try:
        span.update(input=observation.input_payload, output=output_payload)
    except Exception as error:
        logger.warning("Langfuse span 更新失败: %s", type(error).__name__)


def get_langchain_callbacks() -> list[Any]:
    """只在 Agent 根 span 内为 LangChain 模型绑定回调。"""
    if _client is None or not _active_agent_observation.get():
        return []
    try:
        return [_get_callback_handler()()]
    except Exception as error:
        logger.warning("Langfuse CallbackHandler 创建失败: %s", type(error).__name__)
        return []


def shutdown_observability() -> None:
    """关闭客户端并尽量刷新异步上报缓冲。"""
    global _client, _configured

    client, _client = _client, None
    _configured = False
    if client is None:
        return
    try:
        client.shutdown()
    except Exception as error:
        logger.warning("Langfuse 关闭失败: %s", type(error).__name__)


def _reset_observability_for_tests() -> None:
    """重置模块状态，供离线单元测试隔离使用。"""
    global _client, _configured

    _client = None
    _configured = False
    _active_agent_observation.set(False)
    _model_events.set(None)
    _agent_run_id.set(None)
