"""Agent 的可选 Langfuse 观测适配层。"""

import logging
import os
import uuid
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from hashlib import sha256
from math import ceil
from typing import Any, AsyncIterator, Optional, cast
from urllib.parse import urlsplit

from app.security.security import safe_error_message

from observability.runtime_events import (
    ApprovalObservationEvent,
    ExternalIOObservationEvent,
    RUNTIME_EVENT_SCHEMA_VERSION,
    RuntimeObservationEvent,
    ToolObservationEvent,
)

_MODEL_PRICE_ENV = "MODEL_PRICE_REGISTRY"

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



def _read_nested_usage_value(usage: Any, path: str) -> Any:
    """按点分路径读取 usage 字段，兼容 completion_tokens_details.reasoning_tokens 等结构。"""
    current = usage
    for part in path.split("."):
        if current is None:
            return None
        current = current.get(part) if isinstance(current, Mapping) else getattr(current, part, None)
    return current


def _read_usage_value(usage: Any, *names: str) -> int | None:
    """从 dict 或 SDK 对象中按别名读取 token 计数；缺失时返回 None 而不是 0。"""
    for name in names:
        value = _read_nested_usage_value(usage, name)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_token_usage(usage: Any) -> dict[str, int | None]:
    """把 OpenAI、LangChain 与国产兼容服务商的 usage 字段规整为统一键。"""
    input_tokens = _read_usage_value(usage, "input_tokens", "prompt_tokens", "promptTokens")
    output_tokens = _read_usage_value(usage, "output_tokens", "completion_tokens", "completionTokens")
    total_tokens = _read_usage_value(usage, "total_tokens", "totalTokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": _read_usage_value(
            usage,
            "cache_read_tokens",
            "cached_tokens",
            "prompt_cache_hit_tokens",
            "cache_hit_tokens",
        ),
        "reasoning_tokens": _read_usage_value(
            usage,
            "reasoning_tokens",
            "completion_tokens_details.reasoning_tokens",
        ),
    }


def _merge_usage_result(usage: Any) -> dict[str, int | None]:
    """返回标准 token 结构，并在没有有效计数时保留统一的 unavailable 状态。"""
    result = _normalize_token_usage(usage)
    if any(value is not None for value in result.values()):
        return result
    return {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cache_read_tokens": None,
        "reasoning_tokens": None,
    }


def extract_token_usage(value: Any) -> dict[str, int | None]:
    """从 LangChain/OpenAI 响应提取 token 数量，不读取或上报响应正文。"""
    usage = getattr(value, "usage_metadata", None)
    if isinstance(usage, Mapping):
        return _merge_usage_result(usage)
    response_metadata = getattr(value, "response_metadata", None)
    if isinstance(response_metadata, Mapping):
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
        if isinstance(token_usage, Mapping):
            return _merge_usage_result(token_usage)
    raw_usage = getattr(value, "usage", None)
    if raw_usage is not None:
        return _merge_usage_result(raw_usage)
    llm_output = getattr(value, "llm_output", None)
    if isinstance(llm_output, Mapping):
        token_usage = llm_output.get("token_usage") or llm_output.get("usage")
        if isinstance(token_usage, Mapping):
            return _merge_usage_result(token_usage)
    generations = getattr(value, "generations", None)
    if generations:
        try:
            first = generations[0][0]
            message = getattr(first, "message", None)
            usage = getattr(message, "usage_metadata", None)
            if isinstance(usage, Mapping):
                return _merge_usage_result(usage)
            metadata = getattr(message, "response_metadata", None)
            if isinstance(metadata, Mapping):
                token_usage = metadata.get("token_usage") or metadata.get("usage")
                if isinstance(token_usage, Mapping):
                    return _merge_usage_result(token_usage)
        except (IndexError, TypeError):
            pass
    return _merge_usage_result(None)


def _message_role(value: Any) -> str | None:
    """把消息对象映射到固定角色名，避免把任意用户字段名写入观测事件。"""
    role = getattr(value, "role", None) or getattr(value, "type", None)
    if not role and isinstance(value, Mapping):
        role = value.get("role") or value.get("type")
    normalized = str(role or "").lower()
    if normalized in {"system", "human", "user", "ai", "assistant", "tool", "function"}:
        return "human" if normalized == "user" else "ai" if normalized == "assistant" else normalized
    class_name = type(value).__name__.lower()
    for candidate in ("system", "human", "ai", "tool", "function"):
        if candidate in class_name:
            return candidate
    return None


def _content_char_count(value: Any) -> int:
    """递归统计模型可见字符串体积；只返回数量，不序列化或保留原文。"""
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, Mapping):
        if "content" in value:
            return _content_char_count(value.get("content"))
        return sum(_content_char_count(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_content_char_count(item) for item in value)
    content = getattr(value, "content", None)
    if content is not None:
        return _content_char_count(content)
    return len(str(value)) if isinstance(value, (int, float, bool)) else 0


def _content_fingerprint(value: Any) -> str:
    """对模型可见内容做单向哈希；哈希过程不返回或保存原文。"""
    digest = sha256()

    def update(current: Any) -> None:
        """稳定遍历常见消息和结构化输入，加入类型与长度分隔符避免拼接碰撞。"""
        if current is None:
            digest.update(b"none;")
            return
        if isinstance(current, str):
            encoded = current.encode("utf-8")
            digest.update(f"str:{len(encoded)}:".encode("ascii"))
            digest.update(encoded)
            return
        if isinstance(current, bytes):
            digest.update(f"bytes:{len(current)}:".encode("ascii"))
            digest.update(current)
            return
        if isinstance(current, Mapping):
            digest.update(b"mapping{")
            for key in sorted(current, key=lambda item: str(item)):
                digest.update(sha256(str(key).encode("utf-8")).digest())
                update(current[key])
            digest.update(b"}")
            return
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            digest.update(b"sequence[")
            for item in current:
                update(item)
            digest.update(b"]")
            return
        content = getattr(current, "content", None)
        if content is not None:
            digest.update(f"message:{_message_role(current) or 'unknown'}:".encode("ascii"))
            update(content)
            return
        digest.update(f"scalar:{type(current).__name__}:{current!s}".encode("utf-8"))

    update(value)
    return digest.hexdigest()


def measure_model_input(value: Any, *, chars_per_token: float = 4.0) -> dict[str, Any]:
    """生成不含原文的模型输入体积、粗略 token 数、来源分布和指纹。"""
    input_chars = _content_char_count(value)
    source_breakdown: dict[str, int] = {}

    def iter_items(current: Any):
        """展平 LangChain 的批次消息外层，同时保留具体消息对象作为统计单元。"""
        if _message_role(current) is not None or isinstance(current, (str, bytes, Mapping)):
            yield current
            return
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            for child in current:
                yield from iter_items(child)
            return
        yield current

    for item in iter_items(value):
        role = _message_role(item) or "input"
        source_breakdown[role] = source_breakdown.get(role, 0) + _content_char_count(item)
    if not source_breakdown:
        source_breakdown = {"input": input_chars}
    return {
        "input_chars": input_chars,
        "estimated_input_tokens": ceil(input_chars / max(chars_per_token, 0.1)),
        "source_breakdown": source_breakdown,
        "input_fingerprint": _content_fingerprint(value),
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


def _normalize_model_provider(value: Any) -> str | None:
    """把前端供应商 ID 归一到观测维度，避免 aliyun 与 qwen 混用。"""
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in {"aliyun", "dashscope", "bailian", "qwen", "qwq"}:
        return "qwen"
    if raw in {"deepseek", "openai", "openai_compatible", "custom"}:
        return "openai_compatible" if raw == "custom" else raw
    return raw


def provider_observability_metadata(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """从模型通道配置生成不含凭据的 Provider 元数据，供 Langfuse 和本地事件统一使用。"""
    cfg = dict(config or {})
    base_url = str(cfg.get("base_url") or "")
    endpoint = None
    if base_url:
        parsed = urlsplit(base_url)
        endpoint = parsed.netloc or None
    provider = _normalize_model_provider(cfg.get("provider")) or infer_model_provider(cfg.get("model"), base_url)
    return {
        "model_provider": provider,
        "model_integration": cfg.get("integration") or infer_model_integration(cfg.get("model"), base_url, provider),
        "model_endpoint": endpoint,
        "pricing_key": cfg.get("pricing_key") or cfg.get("model"),
    }


def infer_model_provider(model: Any, base_url: str | None = None) -> str:
    """根据显式配置缺失时的模型名和端点推断 Provider，只返回可公开观测的归一化名称。"""
    text = f"{model or ''} {base_url or ''}".lower()
    if "deepseek" in text:
        return "deepseek"
    if any(marker in text for marker in ("dashscope", "aliyun", "bailian", "qwen", "qwq")):
        return "qwen"
    if "openai" in text:
        return "openai"
    return "openai_compatible"


def infer_model_integration(model: Any, base_url: str | None = None, provider: Any = None) -> str:
    """推断模型客户端集成类型；原生服务商优先，网关和自定义端点保持 generic 兜底。"""
    explicit = _normalize_model_provider(provider) or ""
    inferred = infer_model_provider(model, base_url)
    base = (base_url or "").lower()
    if explicit in {"deepseek", "qwen", "openai", "openai_compatible"}:
        inferred = explicit
    if inferred == "deepseek" and (not base or "deepseek" in base):
        return "deepseek"
    if inferred in {"qwen", "aliyun"} and (not base or any(marker in base for marker in ("dashscope", "aliyun"))):
        return "qwen"
    if inferred == "openai" and (not base or "openai" in base):
        return "openai"
    return "openai_compatible"


def _load_price_registry() -> dict[str, dict[str, Any]]:
    """从 JSON 环境变量读取本地模型价格表；解析失败时禁用成本估算但不阻断业务。"""
    raw = os.getenv(_MODEL_PRICE_ENV, "").strip()
    if not raw:
        return {}
    try:
        import json

        parsed = json.loads(raw)
    except Exception as error:
        logger.warning("模型价格表解析失败，跳过成本估算: %s", type(error).__name__)
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for key, value in parsed.items():
        if isinstance(value, Mapping):
            registry[str(key).lower()] = dict(value)
    return registry


def estimate_model_cost(
    *,
    pricing_key: Any = None,
    model_name: Any = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> dict[str, Any]:
    """按本地价格表估算模型成本，默认支持人民币；缺 token 或价格时明确返回 unavailable。"""
    if input_tokens is None or output_tokens is None:
        return {"usage_status": "unavailable", "cost_status": "unavailable"}
    registry = _load_price_registry()
    key_candidates = [str(item).lower() for item in (pricing_key, model_name) if item]
    price = next((registry[key] for key in key_candidates if key in registry), None)
    if not price:
        return {"usage_status": "available", "cost_status": "unpriced"}
    currency = str(price.get("currency") or "CNY").upper()
    try:
        input_per_1m = float(price.get("input_per_1m", 0) or 0)
        output_per_1m = float(price.get("output_per_1m", 0) or 0)
    except (TypeError, ValueError):
        return {"usage_status": "available", "cost_status": "unpriced"}
    estimated = (input_tokens * input_per_1m + output_tokens * output_per_1m) / 1_000_000
    result: dict[str, Any] = {
        "usage_status": "available",
        "cost_status": "estimated",
        "cost_currency": currency,
        "cost_source": "local_pricelist",
    }
    if currency == "CNY":
        result["estimated_cost_cny"] = round(estimated, 8)
    elif currency == "USD":
        result["estimated_cost_usd"] = round(estimated, 8)
    return result


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


def _runtime_percentile(values: Sequence[int], fraction: float) -> int | None:
    """使用最近秩计算运行时事件的小样本百分位。"""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def _terminal_runtime_events(
    events: Sequence[Mapping[str, Any]],
    *,
    prefix: str,
) -> dict[str, Mapping[str, Any]]:
    """按 call ID 保留最后一个终态，避免重试事件被重复计算为多个调用。"""

    terminal_statuses = {"completed", "failed", "blocked", "skipped"}
    terminals: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if not str(event.get("event_type") or "").startswith(prefix):
            continue
        if event.get("status") not in terminal_statuses:
            continue
        call_id = str(event.get("call_id") or event.get("event_id") or "")
        if call_id:
            terminals[call_id] = event
    return terminals


def summarize_tool_events(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """按逻辑 Tool 调用汇总终态、审批风险、耗时和不完整调用。"""

    tool_events = [
        event
        for event in events
        if str(event.get("event_type") or "").startswith("tool.")
    ]
    call_ids = {str(event.get("call_id")) for event in tool_events if event.get("call_id")}
    terminals = _terminal_runtime_events(tool_events, prefix="tool.")
    durations = [
        int(event["duration_ms"])
        for event in terminals.values()
        if isinstance(event.get("duration_ms"), (int, float))
    ]
    slowest = max(
        (
            event
            for event in terminals.values()
            if isinstance(event.get("duration_ms"), (int, float))
        ),
        key=lambda event: int(event.get("duration_ms") or 0),
        default=None,
    )
    return {
        "total": len(call_ids),
        "completed": sum(event.get("status") == "completed" for event in terminals.values()),
        "failed": sum(event.get("status") == "failed" for event in terminals.values()),
        "blocked": sum(event.get("status") == "blocked" for event in terminals.values()),
        "skipped": sum(event.get("status") == "skipped" for event in terminals.values()),
        "incomplete": max(0, len(call_ids) - len(terminals)),
        "approval_required": len(
            {
                str(event.get("call_id"))
                for event in tool_events
                if event.get("requires_confirmation")
            }
        ),
        "external_effect_count": len(
            {
                str(event.get("call_id"))
                for event in tool_events
                if event.get("tool_effect") == "external"
            }
        ),
        "p50_duration_ms": _runtime_percentile(durations, 0.50),
        "p95_duration_ms": _runtime_percentile(durations, 0.95),
        "slowest_tool": slowest.get("tool_name") if slowest else None,
    }


def summarize_external_io_events(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """汇总外部依赖调用的终态、超时和耗时。"""

    io_events = [
        event
        for event in events
        if str(event.get("event_type") or "").startswith("external_io.")
    ]
    call_ids = {str(event.get("call_id")) for event in io_events if event.get("call_id")}
    terminals = _terminal_runtime_events(io_events, prefix="external_io.")
    durations = [
        int(event["duration_ms"])
        for event in terminals.values()
        if isinstance(event.get("duration_ms"), (int, float))
    ]
    return {
        "total": len(call_ids),
        "completed": sum(event.get("status") == "completed" for event in terminals.values()),
        "failed": sum(event.get("status") == "failed" for event in terminals.values()),
        "skipped": sum(event.get("status") == "skipped" for event in terminals.values()),
        "incomplete": max(0, len(call_ids) - len(terminals)),
        "timeout": sum(
            event.get("error_category") == "external_io_timeout"
            for event in terminals.values()
        ),
        "p50_duration_ms": _runtime_percentile(durations, 0.50),
        "p95_duration_ms": _runtime_percentile(durations, 0.95),
    }


def summarize_approval_events(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """汇总审批请求和决定，不暴露审批人身份。"""

    approval_events = [
        event
        for event in events
        if str(event.get("event_type") or "").startswith("approval.")
    ]
    return {
        "requested": sum(event.get("status") == "pending" for event in approval_events),
        "approved": sum(event.get("status") == "approved" for event in approval_events),
        "rejected": sum(event.get("status") == "rejected" for event in approval_events),
    }


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


def summarize_model_events(events: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """按 Agent 汇总 P50/P95、超时率、重试率和 fallback 率。"""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("agent_name") or "unknown"), []).append(event)

    def percentile(values: list[int], fraction: float) -> int | None:
        """使用最近秩计算小样本可解释百分位。"""
        if not values:
            return None
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, ceil(len(ordered) * fraction) - 1))
        return ordered[index]

    summaries: dict[str, dict[str, Any]] = {}
    for agent_name, agent_events in grouped.items():
        started = [item for item in agent_events if item.get("event_type") == "llm.request.started"]
        terminal = [
            item
            for item in agent_events
            if item.get("event_type") in {
                "llm.request.completed",
                "llm.request.failed",
                "llm.request.skipped",
            }
        ]
        durations = [
            int(item["model_duration_ms"])
            for item in terminal
            if isinstance(item.get("model_duration_ms"), (int, float))
        ]
        timeout_count = sum(item.get("failure_type") == "timeout" for item in terminal)
        retry_count = sum(int(item.get("attempt") or 1) > 1 for item in started)
        fallback_count = sum(int(item.get("fallback_index") or 0) > 0 for item in started)
        denominator = max(1, len(started))
        summaries[agent_name] = {
            "call_count": len(started),
            "completed_count": sum(item.get("event_type") == "llm.request.completed" for item in terminal),
            "failed_count": sum(item.get("event_type") != "llm.request.completed" for item in terminal),
            "p50_model_duration_ms": percentile(durations, 0.50),
            "p95_model_duration_ms": percentile(durations, 0.95),
            "timeout_rate": min(timeout_count, denominator) / denominator,
            "retry_rate": retry_count / denominator,
            "fallback_rate": fallback_count / denominator,
        }
    return summaries


def summarize_governance_window(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize one sanitized event window for Phase 6 performance acceptance."""
    started = [event for event in events if event.get("event_type") == "llm.request.started"]
    terminal = [
        event
        for event in events
        if event.get("event_type") in {
            "llm.request.completed",
            "llm.request.failed",
            "llm.request.skipped",
        }
    ]
    durations = sorted(
        int(event["total_duration_ms"])
        for event in terminal
        if isinstance(event.get("total_duration_ms"), (int, float))
    )
    p95_index = max(0, min(len(durations) - 1, ceil(len(durations) * 0.95) - 1))
    denominator = max(1, len(started))
    audited_count = sum(
        isinstance(event.get("input_chars"), (int, float))
        and isinstance(event.get("input_fingerprint"), str)
        and isinstance(event.get("source_breakdown"), Mapping)
        for event in started
    )
    forbidden_fields = {
        "api_key",
        "authorization",
        "cookie",
        "job_description",
        "memory",
        "prompt",
        "resume",
        "token",
        "user_answer",
    }
    return {
        "call_count": len(started),
        "p95_total_duration_ms": durations[p95_index] if durations else None,
        "timeout_rate": sum(
            event.get("failure_type") == "timeout"
            or event.get("error_category") == "external_io_timeout"
            for event in terminal
        ) / denominator,
        "average_fallback_count": sum(
            int(event.get("fallback_index") or 0) > 0
            for event in started
        ) / denominator,
        "context_audit_coverage": audited_count / denominator,
        "unsafe_field_count": sum(
            bool(forbidden_fields.intersection(event))
            for event in events
        ),
    }


def compare_governance_windows(
    baseline_events: Sequence[Mapping[str, Any]],
    current_events: Sequence[Mapping[str, Any]],
    *,
    voice_baseline_chars: int,
    voice_current_chars: int,
    resume_baseline_chars: int,
    resume_current_chars: int,
) -> dict[str, Any]:
    """Compare sanitized before/after windows against the Phase 6 reduction targets."""
    baseline = summarize_governance_window(baseline_events)
    current = summarize_governance_window(current_events)

    def reduction(before: int | float | None, after: int | float | None) -> float:
        """Return a stable reduction ratio; a zero baseline passes only without regression."""
        before_value = float(before or 0)
        after_value = float(after or 0)
        if before_value <= 0:
            return 1.0 if after_value <= 0 else -1.0
        return (before_value - after_value) / before_value

    improvements = {
        "p95_total_duration_reduction": reduction(
            baseline["p95_total_duration_ms"],
            current["p95_total_duration_ms"],
        ),
        "timeout_rate_reduction": reduction(
            baseline["timeout_rate"],
            current["timeout_rate"],
        ),
        "average_fallback_reduction": reduction(
            baseline["average_fallback_count"],
            current["average_fallback_count"],
        ),
        "voice_context_reduction": reduction(
            voice_baseline_chars,
            voice_current_chars,
        ),
        "resume_repeated_input_reduction": reduction(
            resume_baseline_chars,
            resume_current_chars,
        ),
    }
    targets = {
        "p95_total_duration": improvements["p95_total_duration_reduction"] >= 0.30,
        "timeout_rate": improvements["timeout_rate_reduction"] >= 0.70,
        "average_fallback_count": improvements["average_fallback_reduction"] >= 0.50,
        "voice_context": improvements["voice_context_reduction"] >= 0.60,
        "resume_repeated_input": improvements["resume_repeated_input_reduction"] >= 0.50,
        "context_audit_coverage": current["context_audit_coverage"] == 1.0,
        "sensitive_event_fields": current["unsafe_field_count"] == 0,
    }
    return {
        "baseline": baseline,
        "current": current,
        "improvements": improvements,
        "targets": targets,
        "passed": all(targets.values()),
    }


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
