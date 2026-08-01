"""Langfuse 客户端生命周期与 LangChain/LangGraph 回调接线。

客户端缓存、配置、关闭与测试重置都在本模块内维护；共享状态放在
``observability.state``，并统一通过包命名空间在调用期读取，以兼容测试对
``observability._client`` 等包级属性的 monkeypatch。
"""

import logging
from contextlib import contextmanager
from typing import Any

from observability.config import LangfuseConfig
from observability.state import _suppress_direct_llm_callbacks

logger = logging.getLogger(__name__)


def _current_config() -> LangfuseConfig:
    """Return the cached Langfuse config, loading it lazily when needed."""
    import observability

    if observability._config is None:
        observability._config = LangfuseConfig.from_env()
    return observability._config


def configure_langfuse() -> bool:
    """按环境变量初始化 Langfuse，失败时降级为 no-op。"""
    import observability

    if observability._configured:
        return observability._client is not None

    observability._configured = True
    config = LangfuseConfig.from_env()
    observability._config = config
    if not config.enabled:
        return False
    if not config.public_key or not config.secret_key:
        logger.warning("Langfuse 已启用但缺少凭据，观测已降级为 no-op")
        return False

    try:
        observability._client = observability._create_langfuse_client(config)
    except Exception as error:
        logger.warning("Langfuse 初始化失败，观测已降级为 no-op: %s", type(error).__name__)
        observability._client = None
    return observability._client is not None


def shutdown_langfuse() -> None:
    """关闭客户端并尽量刷新异步上报缓冲。"""
    import observability

    client, observability._client = observability._client, None
    observability._config = None
    observability._configured = False
    if client is None:
        return
    try:
        client.shutdown()
    except Exception as error:
        logger.warning("Langfuse 关闭失败: %s", type(error).__name__)


def get_langfuse_client() -> Any | None:
    """Return the configured Langfuse client, initializing it from env if needed."""
    import observability

    if not observability._configured:
        observability.configure_langfuse()
    return observability._client


def _create_callback_handler_instance() -> Any | None:
    """仅在显式允许原始模型 I/O 时创建官方 callback，默认阻断 prompt/output 外发。"""
    import observability

    if observability._client is None or not _current_config().capture_model_io:
        return None
    try:
        return observability._get_callback_handler()()
    except Exception as error:
        logger.warning("Langfuse CallbackHandler 创建失败: %s", type(error).__name__)
        return None


def get_langchain_callbacks() -> list[Any]:
    """为直接 LangChain 模型绑定回调，并在缺少根 span 时创建独立 trace。

    当 LangGraph run 级 callback 已启用时，LangGraph 会通过 config 将
    callback 传播给节点/模型调用。此时抑制直接挂在 ChatOpenAI 上的
    callback，避免同一次 LLM 调用在 Langfuse 中重复上报。
    """
    import observability

    if not observability._configured:
        observability.configure_langfuse()
    if observability._client is None or _suppress_direct_llm_callbacks.get():
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
    import observability

    if not observability._configured:
        observability.configure_langfuse()
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


def _reset_langfuse_for_tests() -> None:
    """重置 Langfuse 模块状态，供离线单元测试隔离使用。"""
    import observability

    observability._client = None
    observability._config = None
    observability._configured = False
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
    from observability.io_tracing import reset_external_io_spans
    from observability.tool_tracing import reset_tool_spans

    reset_external_io_spans()
    reset_tool_spans()
