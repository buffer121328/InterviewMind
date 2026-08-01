"""Agent 的可选 Langfuse 观测适配层。

本模块只做公共 API 的组装与 re-export：业务实现按主题拆在
``callbacks`` / ``events`` / ``observation`` / ``reporting_helpers`` /
``scores`` / ``state`` 等子模块中。
"""

from observability.callbacks import (
    _current_config, _reset_langfuse_for_tests, configure_langfuse,
    get_langchain_callbacks, get_langfuse_client, get_langgraph_callbacks,
    langgraph_langfuse_scope, shutdown_langfuse, with_langgraph_langfuse_config,
)
from observability.config import LangfuseConfig
from observability.events import (
    bind_runtime_event_context, evaluation_model_sink, evaluation_runtime_sink,
    filter_model_call_metadata, get_current_model_call_metadata,
    get_current_model_events, get_current_runtime_events, get_current_trace_id,
    get_runtime_sink_errors, is_agent_observation_active, model_call_metadata_scope,
    record_approval_event, record_external_io_event, record_model_event,
    record_runtime_event, record_tool_event,
)
from observability.langfuse_client import (
    _create_langfuse_client,
    _get_callback_handler,
    _get_propagate_attributes,
)
from observability.observation import (
    _get_agent_run_service, AgentObservation, agent_observation,
)
from observability.privacy import (
    sanitize_trace_payload as _sanitize_trace_payload,
    trace_fingerprint as _trace_fingerprint,
)
from observability.providers import (
    estimate_model_cost, infer_model_integration, infer_model_provider,
    provider_observability_metadata,
)
from observability.reporting_helpers import get_langfuse_trace_url, render_managed_prompt
from observability.runtime_events import (
    ApprovalObservationEvent, ExternalIOObservationEvent,
    RUNTIME_EVENT_SCHEMA_VERSION, RuntimeObservationEvent, ToolObservationEvent,
)
from observability.scores import record_score, record_trace_score
from observability.state import _client, _config, _configured
from observability.summaries import (
    compare_governance_windows, summarize_approval_events,
    summarize_external_io_events, summarize_governance_window,
    summarize_model_events, summarize_tool_events,
)
from observability.usage import extract_token_usage, measure_model_input

__all__ = [
    "AgentObservation",
    "ApprovalObservationEvent", "ExternalIOObservationEvent", "LangfuseConfig",
    "RUNTIME_EVENT_SCHEMA_VERSION", "RuntimeObservationEvent", "ToolObservationEvent",
    "agent_observation", "bind_runtime_event_context", "compare_governance_windows",
    "configure_langfuse", "estimate_model_cost", "evaluation_model_sink",
    "evaluation_runtime_sink", "extract_token_usage", "filter_model_call_metadata",
    "get_current_model_call_metadata", "get_current_model_events",
    "get_current_runtime_events", "get_current_trace_id", "get_langchain_callbacks",
    "get_langfuse_client", "get_langfuse_trace_url", "get_langgraph_callbacks",
    "get_runtime_sink_errors", "infer_model_integration", "infer_model_provider",
    "is_agent_observation_active", "langgraph_langfuse_scope", "measure_model_input",
    "model_call_metadata_scope", "provider_observability_metadata",
    "record_approval_event", "record_external_io_event", "record_model_event",
    "record_runtime_event", "record_score", "record_tool_event", "record_trace_score",
    "render_managed_prompt", "shutdown_langfuse", "summarize_approval_events",
    "summarize_external_io_events", "summarize_governance_window",
    "summarize_model_events", "summarize_tool_events",
    "with_langgraph_langfuse_config",
]
