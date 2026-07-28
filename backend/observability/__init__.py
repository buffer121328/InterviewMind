"""Agent 的可选 Langfuse 观测适配层。"""

import logging
import os
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlsplit


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
_suppress_direct_llm_callbacks: ContextVar[bool] = ContextVar(
    "suppress_direct_llm_callbacks", default=False
)
_client: Any = None
_config: "LangfuseConfig | None" = None
_configured = False


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes"}


def _env_int(name: str, default: int) -> int:
    """Read a positive integer environment variable with a safe fallback."""
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _env_float_optional(name: str) -> float | None:
    """Read an optional float environment variable."""
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class LangfuseConfig:
    """数据对象，承载 `LangfuseConfig` 的结构化字段和跨模块契约；只表达数据，不在构造或序列化时执行外部调用。"""
    enabled: bool
    public_key: str = ""
    secret_key: str = ""
    base_url: str = "https://cloud.langfuse.com"
    environment: str | None = None
    release: str | None = None
    sample_rate: float | None = None
    prompt_management_enabled: bool = False
    prompt_label: str | None = "production"
    prompt_cache_ttl_seconds: int = 300

    @classmethod
    def from_env(cls) -> "LangfuseConfig":
        """从环境变量构造 Langfuse 配置，统一开关、项目和凭据的延迟读取边界。"""
        prompt_label = os.getenv("LANGFUSE_PROMPT_LABEL", "production").strip() or None
        return cls(
            enabled=_env_bool("LANGFUSE_ENABLED"),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            base_url=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
            environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT") or None,
            release=os.getenv("LANGFUSE_RELEASE") or None,
            sample_rate=_env_float_optional("LANGFUSE_SAMPLE_RATE"),
            prompt_management_enabled=_env_bool("LANGFUSE_PROMPT_MANAGEMENT_ENABLED"),
            prompt_label=prompt_label,
            prompt_cache_ttl_seconds=_env_int("LANGFUSE_PROMPT_CACHE_TTL_SECONDS", 300),
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
    """记录 `model event`。

    Args:
        **event: 事件对象。
    """
    events = _model_events.get()
    if events is None:
        return
    safe_event = dict(event)
    safe_event.pop("api_key", None)
    events.append(safe_event)


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

def _create_langfuse_client(config: LangfuseConfig) -> Any:
    """按配置创建 Langfuse 客户端；外部追踪不可用时使用安全降级，不让观测初始化阻断业务流程。

    Args:
        config: 配置对象。
    """
    from langfuse import Langfuse

    return Langfuse(
        public_key=config.public_key,
        secret_key=config.secret_key,
        base_url=config.base_url,
        environment=config.environment,
        release=config.release,
        sample_rate=config.sample_rate,
    )


def _get_agent_run_service() -> Any:
    """获取 AgentRun 持久化服务，用于记录观测关联状态；服务不可用时由调用方遵循不阻断业务的 fallback。"""
    from ai.runtime.agent_runs.service import AgentRunService

    return AgentRunService()


def _get_propagate_attributes():
    """生成 LangChain/Langfuse 传播属性，限制在当前请求的 trace 边界内，不把完整敏感上下文放入外部追踪。"""
    from langfuse import propagate_attributes

    return propagate_attributes


def _get_callback_handler():
    """按当前请求配置创建观测回调处理器；回调只接收脱敏事件，追踪失败不影响主流程返回。"""
    try:
        from langfuse.langchain import CallbackHandler
    except ModuleNotFoundError:
        class CallbackHandler:  # pragma: no cover - 轻量测试环境占位
            """应用或基础设施协作者，负责 `CallbackHandler` 的职责；依赖通过构造或模块边界注入，外部调用、状态持久化和安全校验不向调用方隐藏。"""
            def __call__(self, *args: Any, **kwargs: Any) -> None:
                """实现 `__call__` 协议方法。

                Args:
                    *args: 经过类型边界校验的 `args`；其格式和可选值由参数类型及调用流程约束。
                    **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
                """
                return None

        return CallbackHandler

    return CallbackHandler


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
    """为一次 Agent 执行创建根 span，SDK 故障不影响业务链路。"""
    if not _configured:
        configure_langfuse()

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
    """把观测结果安全地同步到 span；先应用脱敏和字段长度限制，外部追踪失败只记录本地日志。

    Args:
        span: 当前观测对象；更新前会应用脱敏和失败不阻断业务的约束。
        observation: 当前观测对象；更新前会应用脱敏和失败不阻断业务的约束。
    """
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
    """只在 Agent 根 span 内为直接 LangChain 模型绑定回调。

    当 LangGraph run 级 callback 已启用时，LangGraph 会通过 config 将
    callback 传播给节点/模型调用。此时抑制直接挂在 ChatOpenAI 上的
    callback，避免同一次 LLM 调用在 Langfuse 中重复上报。
    """
    if (
        _client is None
        or not _active_agent_observation.get()
        or _suppress_direct_llm_callbacks.get()
    ):
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
    _model_events.set(None)
    _agent_run_id.set(None)
    _suppress_direct_llm_callbacks.set(False)
