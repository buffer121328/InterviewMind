"""Agent 的可选 Langfuse 观测适配层。"""

import logging
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional


logger = logging.getLogger(__name__)
_active_agent_observation: ContextVar[bool] = ContextVar(
    "active_agent_observation", default=False
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
    output_payload: Optional[dict[str, Any]] = None
    error_payload: Optional[dict[str, str]] = None

    def set_output(self, output_payload: dict[str, Any]) -> None:
        self.output_payload = output_payload

    def set_error(self, error: Exception) -> None:
        self.error_payload = {
            "type": type(error).__name__,
            "message": str(error)[:160],
        }


def _create_langfuse_client(config: LangfuseConfig) -> Any:
    from langfuse import Langfuse

    return Langfuse(
        public_key=config.public_key,
        secret_key=config.secret_key,
        base_url=config.base_url,
    )


def _get_propagate_attributes():
    from langfuse import propagate_attributes

    return propagate_attributes


def _get_callback_handler():
    from langfuse.langchain import CallbackHandler

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
) -> AsyncIterator[AgentObservation]:
    """为一次 Agent 执行创建根 span，SDK 故障不影响业务链路。"""
    if not _configured:
        configure_observability()

    observation = AgentObservation(enabled=_client is not None, input_payload=input_payload)
    if _client is None:
        yield observation
        return

    entered = False
    business_error = False
    try:
        propagate_attributes = _get_propagate_attributes()
        with _client.start_as_current_observation(as_type="span", name=name) as span:
            with propagate_attributes(
                trace_name=name,
                user_id=user_id,
                session_id=session_id,
                metadata={"agent_type": agent_type},
            ):
                entered = True
                token = _active_agent_observation.set(True)
                try:
                    yield observation
                except Exception as error:
                    business_error = True
                    observation.set_error(error)
                    raise
                finally:
                    _active_agent_observation.reset(token)
                    _update_span(span, observation)
    except Exception as error:
        if business_error:
            raise
        logger.warning("Langfuse 观测失败，业务继续执行: %s", type(error).__name__)
        if not entered:
            yield AgentObservation(enabled=False, input_payload=input_payload)


def _update_span(span: Any, observation: AgentObservation) -> None:
    output_payload = observation.output_payload or {}
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
