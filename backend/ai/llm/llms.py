"""模型网关。

已知超限：职责单一（模型网关），暂不拆分。
"""

from __future__ import annotations

import asyncio
import logging
import os
from hashlib import sha256
from threading import RLock
from time import perf_counter, time
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from langchain_qwq import ChatQwen

from ai.llm.model_pool import ModelPoolScheduler, _identity, _ModelPoolCallback
from ai.runtime.deadlines import (
    TaskDeadline,
    TaskDeadlineExceeded,
    get_current_task_deadline,
)
from ai.runtime.error_classification import classify_exception
from app.config import get_settings
from app.security.url_security import validate_outbound_url
from observability import (
    estimate_model_cost,
    extract_token_usage,
    filter_model_call_metadata,
    get_langchain_callbacks,
    infer_model_integration,
    measure_model_input,
    model_call_metadata_scope,
    provider_observability_metadata,
    record_model_event,
)
# ============================================================================
# 动态 LLM 创建（支持用户自定义配置）
# ============================================================================

def _llm_metadata(config: dict[str, Any]) -> dict[str, Any]:
    """生成传给 LangChain/Langfuse 的安全模型元数据，不包含 API Key 或完整私有地址。"""
    metadata = provider_observability_metadata(config)
    metadata.update({"model_name": config.get("model")})
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _attach_llm_observability_attrs(llm: object, metadata: dict[str, Any]) -> None:
    """把统一模型身份附着到 LLM 实例，供 wrapper 失败路径和测试读取。"""
    for key, value in metadata.items():
        try:
            object.__setattr__(llm, f"_{key}", value)
        except Exception:
            continue


def create_llm_from_config(
    api_key: str,
    base_url: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    extra_callbacks: Optional[list[Any]] = None,
    timeout: Optional[int] = None,
    provider: str | None = None,
    integration: str | None = None,
    pricing_key: str | None = None,
    **_: Any,
) -> BaseChatModel:
    """根据用户配置创建 provider-aware LLM；原生 DeepSeek/Qwen 优先，OpenAI-compatible 兜底。"""
    settings = get_settings()
    validate_outbound_url(base_url, allow_private=settings.allow_private_model_base_urls)
    config = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "provider": provider,
        "integration": integration,
        "pricing_key": pricing_key,
    }
    metadata = _llm_metadata(config)
    selected_integration = str(integration or metadata.get("model_integration") or infer_model_integration(model, base_url, provider))
    callbacks = list(get_langchain_callbacks())
    if extra_callbacks:
        callbacks.extend(extra_callbacks)
    common_options: dict[str, Any] = {
        "temperature": temperature,
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "api_key": api_key,
        "base_url": base_url,
        # 由调用层负责有限重试，避免 SDK 重试与 fallback 叠加导致长时间阻塞。
        "timeout": timeout or settings.llm_request_timeout_seconds,
        "max_retries": 0,
        "metadata": metadata,
        "tags": [f"provider:{metadata.get('model_provider', 'unknown')}", f"integration:{selected_integration}"],
    }
    if callbacks:
        common_options["callbacks"] = callbacks

    if selected_integration == "deepseek":
        llm: BaseChatModel = ChatDeepSeek(model=model, **common_options)
    elif selected_integration == "qwen":
        llm = ChatQwen(model=model, **common_options)
    else:
        llm = ChatOpenAI(model_name=model, **common_options)
    _attach_llm_observability_attrs(llm, metadata)
    if extra_callbacks:
        object.__setattr__(llm, "_model_pool_callback_managed", True)
    return llm


def _resolve_channel_config(api_config: dict, channel: str) -> dict:
    """按通道定义解析用户模型配置。"""
    import logging

    logger = logging.getLogger(__name__)
    fallback_chain = [channel, "general", "smart"]
    for ch in fallback_chain:
        config = api_config.get(ch)
        if config and config.get("api_key"):
            if ch != channel:
                logger.info("[LLM] 通道 %s 未配置，回退到 %s", channel, ch)
            return config
    raise ValueError(f"未检测到 {channel.upper()} 通道的 API 配置。请在设置中配置请求通道模型。")


def _valid_model_channel(config: dict | None) -> dict | None:
    """Return a complete OpenAI-compatible model channel config, or None."""
    if not isinstance(config, dict):
        return None
    if config.get("api_key") and config.get("base_url") and config.get("model"):
        return config
    return None


def get_embedding_client_config_from_api_config(api_config: dict | None = None) -> dict:
    """Resolve RAG embedding config from request api_config, falling back to env."""
    request_config = _valid_model_channel((api_config or {}).get("rag_embedding"))
    if request_config:
        return {
            "api_key": request_config["api_key"],
            "base_url": request_config["base_url"],
            "model": request_config["model"],
            "dimensions": int(os.getenv("EMBEDDING_DIM", "1536")),
        }
    return {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": os.getenv("EMBEDDING_MODEL", "text-embedding-v4"),
        "dimensions": int(os.getenv("EMBEDDING_DIM", "1536")),
    }


class ModelGateway:
    """模型网关：Redis 全局调度优先，通道回退与进程内降级。"""

    def __init__(self) -> None:
        """初始化 `ModelGateway` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self.scheduler = ModelPoolScheduler()
        self._candidate_identities: dict[int, str] = {}
        self._candidate_lock = RLock()

    def _bind_identity(self, llm: object, identity: str) -> None:
        """把当前请求的身份配置绑定到模型调用上下文，不把凭据写入共享状态。

        Args:
            llm: 语言模型实例。
            identity: 经过类型边界校验的 `identity`；其格式和可选值由参数类型及调用流程约束。
        """
        try:
            object.__setattr__(llm, "_model_pool_identity", identity)
        except Exception:
            with self._candidate_lock:
                self._candidate_identities[id(llm)] = identity

    def _take_identity(self, llm: object) -> str | None:
        """从当前异步上下文取出模型身份，并在调用结束后由调用方恢复上下文。

        Args:
            llm: 语言模型实例。
        """
        identity = getattr(llm, "_model_pool_identity", None)
        if identity:
            try:
                object.__setattr__(llm, "_model_pool_identity", None)
            except Exception:
                pass
            return identity
        with self._candidate_lock:
            return self._candidate_identities.pop(id(llm), None)

    @staticmethod
    def _pool(api_config: dict, name: str, fallback_channel: str) -> list[dict]:
        """返回按名称选择的模型池，并集中应用池为空和配置缺失时的 fallback。

        Args:
            api_config: api 配置。
            name: 名称。
            fallback_channel: 经过类型边界校验的 `fallback_channel`；其格式和可选值由参数类型及调用流程约束。
        """
        configured = [dict(item) for item in api_config.get(name, []) if item and item.get("api_key")]
        if configured:
            return configured
        fallback = api_config.get(fallback_channel)
        return [dict(fallback)] if fallback and fallback.get("api_key") else []

    def _candidate_configs(self, api_config: dict, channel: str) -> tuple[list[dict], str | None]:
        """从请求配置解析可用模型候选，并保留模型网关的 URL、超时和冷却约束。

        Args:
            api_config: api 配置。
            channel: 经过类型边界校验的 `channel`；其格式和可选值由参数类型及调用流程约束。
        """
        fast_pool = self._pool(api_config, "fast_pool", "fast")
        reasoning_pool = self._pool(api_config, "reasoning_pool", "smart")

        groups: list[tuple[str, list[dict]]] = []
        if channel == "fast":
            groups.append(("fast_pool", fast_pool))
        elif channel == "smart":
            groups.append(("reasoning_pool", reasoning_pool))
        else:
            direct = api_config.get(channel)
            if direct and direct.get("api_key"):
                groups.append((f"channel:{channel}", [dict(direct)]))

        general = api_config.get("general")
        if channel != "general" and general and general.get("api_key"):
            groups.append(("channel:general", [dict(general)]))
        if channel != "smart":
            groups.append(("reasoning_pool", reasoning_pool))
        if channel != "fast":
            groups.append(("fast_pool", fast_pool))

        ordered: list[dict] = []
        seen: set[str] = set()
        reserved_identity: str | None = None
        for pool_name, configs in groups:
            if not configs:
                continue
            if reserved_identity is None:
                group_order, reserved_identity = self.scheduler.reserve_order(pool_name, configs)
            else:
                group_order = self.scheduler.order(pool_name, configs)
            for config in group_order:
                identity = _identity(config)
                if identity not in seen:
                    ordered.append(config)
                    seen.add(identity)
        return ordered, reserved_identity

    def get_chat_candidates(
        self,
        api_config: Optional[dict],
        channel: str = "smart",
        *,
        temperature: float = 0.7,
    ) -> list[BaseChatModel]:
        """读取 chat candidates，并保持调用方的错误和生命周期边界；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            api_config: api 配置。
            channel: 经过类型边界校验的 `channel`；其格式和可选值由参数类型及调用流程约束。
        """
        if not api_config:
            raise ValueError("未检测到 API 配置。请在设置中配置您的大模型 API 后再使用本功能。")
        configs, reserved_identity = self._candidate_configs(api_config, channel)
        if not configs:
            configs = [_resolve_channel_config(api_config, channel)]
            configs, reserved_identity = self.scheduler.reserve_order(f"channel:{channel}", configs)

        candidates: list[BaseChatModel] = []
        candidate_count = len(configs)
        for candidate_index, config in enumerate(configs, start=1):
            output_token_limit = get_settings().llm_max_tokens
            llm = create_llm_from_config(
                api_key=config["api_key"],
                base_url=config["base_url"],
                model=config["model"],
                temperature=temperature,
                max_tokens=output_token_limit,
                provider=config.get("provider"),
                integration=config.get("integration"),
                pricing_key=config.get("pricing_key"),
                extra_callbacks=[_ModelPoolCallback(
                    self.scheduler,
                    _identity(config),
                    pre_reserved=_identity(config) == reserved_identity,
                    channel=channel,
                    model_name=config["model"],
                    provider_metadata=provider_observability_metadata(config),
                    candidate_count=candidate_count,
                    candidate_index=candidate_index,
                    output_token_limit=output_token_limit,
                )],
            )
            self._bind_identity(llm, _identity(config))
            candidates.append(llm)
        return candidates

    def get_chat_model(self, api_config: Optional[dict], channel: str = "smart") -> BaseChatModel:
        """读取 chat model，并保持调用方的错误和生命周期边界；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            api_config: api 配置。
            channel: 经过类型边界校验的 `channel`；其格式和可选值由参数类型及调用流程约束。
        """
        return self.get_chat_candidates(api_config, channel)[0]

    def record_chat_success(self, llm: object) -> None:
        """记录 `chat success`。

        Args:
            llm: 语言模型实例。
        """
        identity = self._take_identity(llm)
        if identity and not getattr(llm, "_model_pool_callback_managed", False):
            self.scheduler.record_success(identity)

    def record_chat_failure(self, llm: object) -> None:
        """记录 `chat failure`。

        Args:
            llm: 语言模型实例。
        """
        identity = self._take_identity(llm)
        if identity and not getattr(llm, "_model_pool_callback_managed", False):
            self.scheduler.record_failure(identity)

    def get_embedding_request_options(self, model: str | None = None, dimensions: int | None = None) -> dict:
        """读取 embedding request options，并保持调用方的错误和生命周期边界；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            model: 模型对象。
            dimensions: 经过类型边界校验的 `dimensions`；其格式和可选值由参数类型及调用流程约束。
        """
        return {
            "model": model or os.getenv("EMBEDDING_MODEL", "text-embedding-v4"),
            "dimensions": dimensions or int(os.getenv("EMBEDDING_DIM", "1536")),
        }

    def get_embedding_client_config(
        self,
        model: str | None = None,
        dimensions: int | None = None,
        api_config: dict | None = None,
    ) -> dict:
        """读取 embedding client config，并保持调用方的错误和生命周期边界；资源不存在或状态不合法时返回稳定的业务结果或异常。

        Args:
            model: 模型对象。
            dimensions: 经过类型边界校验的 `dimensions`；其格式和可选值由参数类型及调用流程约束。
            api_config: 前端请求携带的模型配置。
        """
        config = get_embedding_client_config_from_api_config(api_config)
        return {
            **config,
            **self.get_embedding_request_options(model=model or config["model"], dimensions=dimensions or config["dimensions"]),
        }

    async def create_embeddings(
        self,
        input_value: str | list[str],
        model: str | None = None,
        dimensions: int | None = None,
        api_config: dict | None = None,
    ):
        """创建 embeddings，在写入前沿用请求的 owner、审批和输入校验边界，并返回调用方可继续处理的结果。

        Args:
            input_value: 经过类型边界校验的 `input_value`；其格式和可选值由参数类型及调用流程约束。
            model: 模型对象。
            dimensions: 经过类型边界校验的 `dimensions`；其格式和可选值由参数类型及调用流程约束。
        """
        config = self.get_embedding_client_config(model=model, dimensions=dimensions, api_config=api_config)
        identity = _identity(config)
        safe_identity = sha256(identity.encode("utf-8")).hexdigest()[:16]
        input_metrics = measure_model_input(
            input_value,
            chars_per_token=get_settings().llm_estimated_chars_per_token,
        )
        self.scheduler.start(identity)
        started = time()
        record_model_event(
            event_type="embedding.request.started",
            channel="embedding",
            model_name=config.get("model"),
            **provider_observability_metadata(config),
            model_member=safe_identity,
            candidate_count=1,
            candidate_index=1,
            fallback_index=0,
            item_count=1 if isinstance(input_value, str) else len(input_value),
            **input_metrics,
        )
        try:
            client = create_embedding_client(config)
            response = await client.embeddings.create(
                input=input_value,
                **self.get_embedding_request_options(model=config["model"], dimensions=config["dimensions"]),
            )
            self.scheduler.record_success(identity)
            usage = extract_token_usage(response)
            cost = estimate_model_cost(
                pricing_key=provider_observability_metadata(config).get("pricing_key"),
                model_name=config.get("model"),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            )
            duration_ms = max(0, int((time() - started) * 1000))
            record_model_event(
                event_type="embedding.request.completed",
                channel="embedding",
                model_name=config.get("model"),
                **provider_observability_metadata(config),
                model_member=safe_identity,
                candidate_count=1,
                candidate_index=1,
                fallback_index=0,
                item_count=1 if isinstance(input_value, str) else len(input_value),
                duration_ms=duration_ms,
                model_duration_ms=duration_ms,
                total_duration_ms=duration_ms,
                **input_metrics,
                **usage,
                **cost,
            )
            return response
        except Exception as exc:
            self.scheduler.record_failure(identity)
            classified = classify_exception(exc)
            duration_ms = max(0, int((time() - started) * 1000))
            record_model_event(
                event_type="embedding.request.failed",
                channel="embedding",
                model_name=config.get("model"),
                **provider_observability_metadata(config),
                model_member=safe_identity,
                candidate_count=1,
                candidate_index=1,
                fallback_index=0,
                item_count=1 if isinstance(input_value, str) else len(input_value),
                duration_ms=duration_ms,
                model_duration_ms=duration_ms,
                total_duration_ms=duration_ms,
                **input_metrics,
                error_type=type(exc).__name__,
                error_category=classified.category.value,
                error_code=classified.code,
                failure_type=classified.failure_type.value,
            )
            raise


model_gateway = ModelGateway()


def get_llm_for_request(api_config: Optional[dict] = None, channel: str = "smart") -> BaseChatModel:
    """读取 llm for request，并保持调用方的错误和生命周期边界；资源不存在或状态不合法时返回稳定的业务结果或异常。

    Args:
        api_config: api 配置。
        channel: 经过类型边界校验的 `channel`；其格式和可选值由参数类型及调用流程约束。
    """
    import logging

    logging.getLogger(__name__).info("[LLM] 请求通道: %s", channel)
    return model_gateway.get_chat_model(api_config, channel)


def create_embedding_client(config: dict):
    """创建 OpenAI-compatible embedding 客户端。"""
    from openai import AsyncOpenAI

    if not config or not config.get("api_key"):
        raise ValueError("未检测到 Embedding API 配置")
    base_url = config.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    validate_outbound_url(base_url, allow_private=get_settings().allow_private_model_base_urls)
    return AsyncOpenAI(
        api_key=config["api_key"],
        base_url=base_url,
        timeout=get_settings().llm_request_timeout_seconds,
        max_retries=0,
    )


async def invoke_text(
    input_value: object,
    api_config: Optional[dict] = None,
    channel: str = "smart",
    *,
    timeout: float | None = None,
    deadline: TaskDeadline | None = None,
    call_metadata: dict[str, Any] | None = None,
):
    """普通文本统一 fallback；显式或上下文 deadline 会跨候选持续递减。"""
    candidates = model_gateway.get_chat_candidates(api_config, channel)
    settings = get_settings()
    request_timeout = timeout or settings.llm_request_timeout_seconds
    task_deadline = deadline or get_current_task_deadline()
    if task_deadline is None and settings.task_deadline_enabled:
        task_deadline = TaskDeadline(settings.llm_task_timeout_seconds)
    audit_metadata = filter_model_call_metadata(call_metadata)

    def record_attempt_failure(
        candidate: object,
        index: int,
        error: BaseException,
        duration_ms: int,
        runtime_metadata: dict[str, Any],
    ) -> None:
        """记录普通文本 wrapper 的稳定失败类型，不保存输入或错误原文。"""
        classified = classify_exception(error)
        identity = getattr(candidate, "_model_pool_identity", "") or ""
        payload = {
            **runtime_metadata,
            **measure_model_input(
                input_value,
                chars_per_token=settings.llm_estimated_chars_per_token,
            ),
            **audit_metadata,
            "event_type": "llm.request.failed",
            "channel": channel,
            "model_name": getattr(candidate, "model_name", None) or getattr(candidate, "model", None),
            "model_member": sha256(str(identity).encode("utf-8")).hexdigest()[:16] if identity else None,
            "candidate_count": len(candidates),
            "candidate_index": index + 1,
            "fallback_index": index,
            "error_type": type(error).__name__,
            "error_category": classified.category.value,
            "error_code": classified.code,
            "failure_type": classified.failure_type.value,
            "duration_ms": duration_ms,
            "model_duration_ms": duration_ms,
            "total_duration_ms": duration_ms,
        }
        record_model_event(**payload)

    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        effective_timeout = float(request_timeout)
        if task_deadline is not None:
            effective_timeout = task_deadline.timeout_for_next_attempt(
                request_timeout,
                minimum_required=settings.llm_min_attempt_timeout_seconds,
            )
            if effective_timeout <= 0:
                metrics = measure_model_input(
                    input_value,
                    chars_per_token=settings.llm_estimated_chars_per_token,
                )
                record_model_event(**{
                    **metrics,
                    **audit_metadata,
                    "event_type": "llm.request.skipped",
                    "channel": channel,
                    "candidate_count": len(candidates),
                    "candidate_index": index + 1,
                    "fallback_index": index,
                    "attempt": 1,
                    "deadline_ms": task_deadline.deadline_ms,
                    "deadline_remaining_ms": task_deadline.remaining_ms,
                    "failure_type": "timeout",
                    "error_type": "TaskDeadlineExceeded",
                })
                last_error = TaskDeadlineExceeded("task deadline exhausted before next model candidate")
                break
        runtime_metadata = {
            "attempt": 1,
            "deadline_ms": task_deadline.deadline_ms if task_deadline else None,
            "deadline_remaining_ms": task_deadline.remaining_ms if task_deadline else None,
            "queue_wait_ms": 0,
            "wrapper_managed": True,
        }
        metadata = {
            **runtime_metadata,
            **audit_metadata,
        }
        started_at = perf_counter()
        try:
            with model_call_metadata_scope(**metadata):
                return await asyncio.wait_for(candidate.ainvoke(input_value), timeout=effective_timeout)
        except asyncio.CancelledError as exc:
            duration_ms = max(0, int((perf_counter() - started_at) * 1000))
            record_attempt_failure(
                candidate,
                index,
                exc,
                duration_ms,
                runtime_metadata,
            )
            raise
        except Exception as exc:
            last_error = exc
            classified = classify_exception(exc)
            duration_ms = max(0, int((perf_counter() - started_at) * 1000))
            record_attempt_failure(
                candidate,
                index,
                exc,
                duration_ms,
                runtime_metadata,
            )
            logging.getLogger(__name__).warning(
                "[LLM] 文本调用失败，切换候选: channel=%s candidate=%s error=%s",
                channel, index + 1, type(exc).__name__,
            )
            if not classified.fallback_allowed:
                break
    if last_error is not None:
        raise last_error
    raise RuntimeError("没有可用的模型候选")
