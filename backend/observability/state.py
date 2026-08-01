"""Langfuse 观测适配层的共享运行时状态。

ContextVar 在请求/任务边界内传播观测上下文；``_client`` / ``_config`` /
``_configured`` 缓存 Langfuse 客户端与配置。各子模块通过
``import observability`` 在调用期读取这些状态，以兼容测试对
``observability._client`` 等包级属性的 monkeypatch。
"""

from contextvars import ContextVar
from typing import Any

from observability.config import LangfuseConfig

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
