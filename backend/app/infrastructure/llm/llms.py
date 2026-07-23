from __future__ import annotations

import asyncio
import logging
import os
from threading import RLock
from time import time
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.infrastructure.llm.model_pool import ModelPoolScheduler, _ModelPoolCallback, _identity
from app.langfuse import extract_token_usage, get_langchain_callbacks, record_model_event
from app.infrastructure.security.url_security import validate_outbound_url


# ============================================================================
# 动态 LLM 创建（支持用户自定义配置）
# ============================================================================

def create_llm_from_config(
    api_key: str,
    base_url: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    extra_callbacks: Optional[list[Any]] = None,
    timeout: Optional[int] = None,
    **_: Any,
) -> ChatOpenAI:
    """根据用户提供的 OpenAI-compatible 配置创建 LLM 实例。"""
    settings = get_settings()
    validate_outbound_url(base_url, allow_private=settings.allow_private_model_base_urls)
    options = {
        "temperature": temperature,
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "model_name": model,
        "api_key": api_key,
        "base_url": base_url,
        # 由调用层负责有限重试，避免 SDK 重试与 fallback 叠加导致长时间阻塞。
        "timeout": timeout or settings.llm_request_timeout_seconds,
        "max_retries": 0,
    }
    callbacks = list(get_langchain_callbacks())
    if extra_callbacks:
        callbacks.extend(extra_callbacks)
    if callbacks:
        options["callbacks"] = callbacks
    llm = ChatOpenAI(**options)
    if extra_callbacks:
        object.__setattr__(llm, "_model_pool_callback_managed", True)
    return llm


def _resolve_channel_config(api_config: dict, channel: str) -> dict:
    """按通道定义解析用户模型配置。"""
    import logging

    logger = logging.getLogger(__name__)
    fallback_chain = ["voice", "fast"] if channel == "voice" else [channel, "general", "smart"]
    for ch in fallback_chain:
        config = api_config.get(ch)
        if config and config.get("api_key"):
            if ch != channel:
                logger.info("[LLM] 通道 %s 未配置，回退到 %s", channel, ch)
            return config
    if channel == "voice":
        raise ValueError("未检测到 VOICE 通道的 API 配置。请在设置中选择语音模型。")
    raise ValueError(f"未检测到 {channel.upper()} 通道的 API 配置。请在设置中配置请求通道模型。")


class ModelGateway:
    """模型网关：Redis 全局调度优先，通道回退与进程内降级。"""

    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self.scheduler = ModelPoolScheduler()
        self._candidate_identities: dict[int, str] = {}
        self._candidate_lock = RLock()

    def _bind_identity(self, llm: object, identity: str) -> None:
        """执行 `_bind_identity` 相关逻辑。

        Args:
            llm: 语言模型实例。
            identity: 调用方传入的 `identity` 参数。
        """
        try:
            object.__setattr__(llm, "_model_pool_identity", identity)
        except Exception:
            with self._candidate_lock:
                self._candidate_identities[id(llm)] = identity

    def _take_identity(self, llm: object) -> str | None:
        """执行 `_take_identity` 相关逻辑。

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
        """执行 `_pool` 相关逻辑。

        Args:
            api_config: api 配置。
            name: 名称。
            fallback_channel: 调用方传入的 `fallback_channel` 参数。
        """
        configured = [dict(item) for item in api_config.get(name, []) if item and item.get("api_key")]
        if configured:
            return configured
        fallback = api_config.get(fallback_channel)
        return [dict(fallback)] if fallback and fallback.get("api_key") else []

    def _candidate_configs(self, api_config: dict, channel: str) -> tuple[list[dict], str | None]:
        """执行 `_candidate_configs` 相关逻辑。

        Args:
            api_config: api 配置。
            channel: 调用方传入的 `channel` 参数。
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

    def get_chat_candidates(self, api_config: Optional[dict], channel: str = "smart") -> list[ChatOpenAI]:
        """获取 `chat candidates`。

        Args:
            api_config: api 配置。
            channel: 调用方传入的 `channel` 参数。
        """
        if not api_config:
            raise ValueError("未检测到 API 配置。请在设置中配置您的大模型 API 后再使用本功能。")
        configs, reserved_identity = self._candidate_configs(api_config, channel)
        if not configs:
            configs = [_resolve_channel_config(api_config, channel)]
            configs, reserved_identity = self.scheduler.reserve_order(f"channel:{channel}", configs)

        candidates: list[ChatOpenAI] = []
        for config in configs:
            llm = create_llm_from_config(
                api_key=config["api_key"],
                base_url=config["base_url"],
                model=config["model"],
                max_tokens=get_settings().llm_max_tokens,
                extra_callbacks=[_ModelPoolCallback(
                    self.scheduler,
                    _identity(config),
                    pre_reserved=_identity(config) == reserved_identity,
                )],
            )
            self._bind_identity(llm, _identity(config))
            candidates.append(llm)
        return candidates

    def get_chat_model(self, api_config: Optional[dict], channel: str = "smart") -> ChatOpenAI:
        """获取 `chat model`。

        Args:
            api_config: api 配置。
            channel: 调用方传入的 `channel` 参数。
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

    def get_voice_client(self, api_config: dict):
        """获取 `voice client`。

        Args:
            api_config: api 配置。
        """
        voice_config = _resolve_channel_config(api_config, "voice")
        return get_async_omni_client(voice_config)

    def get_voice_request_options(self, api_config: dict, voice_config: dict | None = None) -> dict:
        """获取 `voice request options`。

        Args:
            api_config: api 配置。
            voice_config: voice 配置。
        """
        settings = get_settings()
        selected = voice_config or api_config.get("voice") or {}
        return {
            "model": selected.get("model") or settings.voice_model,
            "modalities": ["text", "audio"],
            "audio": {"voice": settings.voice_name, "format": settings.voice_output_format},
        }

    def _voice_candidate_configs(self, api_config: dict) -> tuple[list[dict], str | None]:
        """执行 `_voice_candidate_configs` 相关逻辑。

        Args:
            api_config: api 配置。
        """
        settings = get_settings()
        groups: list[tuple[str, list[dict]]] = []
        voice_config = api_config.get("voice")
        if voice_config and voice_config.get("api_key"):
            groups.append(("channel:voice", [dict(voice_config)]))

        fast_fallbacks = [
            {**config, "model": settings.voice_model}
            for config in self._pool(api_config, "fast_pool", "fast")
        ]
        if fast_fallbacks:
            groups.append(("voice:fallback_fast", fast_fallbacks))

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

        if not ordered:
            # 保留旧错误语义：既无 voice 也无 fast 时提示语音通道缺失。
            config = _resolve_channel_config(api_config, "voice")
            ordered.append({**config, "model": config.get("model") or settings.voice_model})
        return ordered, reserved_identity

    async def stream_voice_chat_completions(
        self,
        api_config: dict,
        *,
        messages: list[dict],
        stream_options: dict | None = None,
    ):
        """流式处理 `voice chat completions`。

        Args:
            api_config: api 配置。
            messages: 消息列表。
            stream_options: 调用方传入的 `stream_options` 参数。
        """
        configs, reserved_identity = self._voice_candidate_configs(api_config)
        last_error: Exception | None = None
        for index, config in enumerate(configs):
            identity = _identity(config)
            model_name = config.get("model")
            if identity != reserved_identity:
                self.scheduler.start(identity)
            yielded = False
            started = time()
            record_model_event(
                event_type="voice.request.started",
                channel="voice",
                model_name=model_name,
                model_member=identity,
                candidate_index=index + 1,
            )
            try:
                client = get_async_omni_client(config)
                completion = await client.chat.completions.create(
                    messages=messages,
                    stream=True,
                    stream_options=stream_options or {"include_usage": True},
                    **self.get_voice_request_options(api_config, config),
                )
                last_chunk = None
                async for chunk in completion:
                    yielded = True
                    last_chunk = chunk
                    yield chunk
                self.scheduler.record_success(identity)
                usage = extract_token_usage(last_chunk) if last_chunk is not None else {"input_tokens": None, "output_tokens": None}
                record_model_event(
                    event_type="voice.request.completed",
                    channel="voice",
                    model_name=model_name,
                    model_member=identity,
                    candidate_index=index + 1,
                    duration_ms=max(0, int((time() - started) * 1000)),
                    **usage,
                )
                return
            except Exception as exc:
                self.scheduler.record_failure(identity)
                last_error = exc
                record_model_event(
                    event_type="voice.request.failed",
                    channel="voice",
                    model_name=model_name,
                    model_member=identity,
                    candidate_index=index + 1,
                    duration_ms=max(0, int((time() - started) * 1000)),
                    error_type=type(exc).__name__,
                )
                if yielded:
                    raise
                logging.getLogger(__name__).warning(
                    "[LLM] Voice 调用失败，切换候选: candidate=%s error=%s",
                    index + 1, type(exc).__name__,
                )
        if last_error is not None:
            raise last_error
        raise RuntimeError("没有可用的语音模型候选")

    def get_voice_input_format(self) -> str:
        """获取 `voice input format`。"""
        return get_settings().voice_input_format

    def get_embedding_request_options(self, model: str | None = None, dimensions: int | None = None) -> dict:
        """获取 `embedding request options`。

        Args:
            model: 模型对象。
            dimensions: 调用方传入的 `dimensions` 参数。
        """
        return {
            "model": model or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            "dimensions": dimensions or int(os.getenv("EMBEDDING_DIM", "1536")),
        }

    def get_embedding_client_config(self, model: str | None = None, dimensions: int | None = None) -> dict:
        """获取 `embedding client config`。

        Args:
            model: 模型对象。
            dimensions: 调用方传入的 `dimensions` 参数。
        """
        return {
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            **self.get_embedding_request_options(model=model, dimensions=dimensions),
        }

    async def create_embeddings(self, input_value: str | list[str], model: str | None = None, dimensions: int | None = None):
        """创建 `embeddings`。

        Args:
            input_value: 调用方传入的 `input_value` 参数。
            model: 模型对象。
            dimensions: 调用方传入的 `dimensions` 参数。
        """
        config = self.get_embedding_client_config(model=model, dimensions=dimensions)
        identity = _identity(config)
        self.scheduler.start(identity)
        started = time()
        record_model_event(
            event_type="embedding.request.started",
            channel="embedding",
            model_name=config.get("model"),
            model_member=identity,
        )
        try:
            client = create_embedding_client(config)
            response = await client.embeddings.create(
                input=input_value,
                **self.get_embedding_request_options(model=config["model"], dimensions=config["dimensions"]),
            )
            self.scheduler.record_success(identity)
            usage = extract_token_usage(response)
            record_model_event(
                event_type="embedding.request.completed",
                channel="embedding",
                model_name=config.get("model"),
                model_member=identity,
                duration_ms=max(0, int((time() - started) * 1000)),
                **usage,
            )
            return response
        except Exception as exc:
            self.scheduler.record_failure(identity)
            record_model_event(
                event_type="embedding.request.failed",
                channel="embedding",
                model_name=config.get("model"),
                model_member=identity,
                duration_ms=max(0, int((time() - started) * 1000)),
                error_type=type(exc).__name__,
            )
            raise


model_gateway = ModelGateway()


def get_llm_for_request(api_config: Optional[dict] = None, channel: str = "smart") -> ChatOpenAI:
    """获取 `llm for request`。

    Args:
        api_config: api 配置。
        channel: 调用方传入的 `channel` 参数。
    """
    import logging

    logging.getLogger(__name__).info("[LLM] 请求通道: %s", channel)
    return model_gateway.get_chat_model(api_config, channel)


def create_embedding_client(config: dict):
    """创建 OpenAI-compatible embedding 客户端。"""
    from openai import AsyncOpenAI

    if not config or not config.get("api_key"):
        raise ValueError("未检测到 Embedding API 配置")
    base_url = config.get("base_url") or "https://api.openai.com/v1"
    validate_outbound_url(base_url, allow_private=get_settings().allow_private_model_base_urls)
    return AsyncOpenAI(
        api_key=config["api_key"],
        base_url=base_url,
        timeout=get_settings().llm_request_timeout_seconds,
        max_retries=0,
    )


def get_async_omni_client(voice_config: dict):
    """根据前端传入的配置创建异步 OpenAI 客户端。"""
    from openai import AsyncOpenAI

    if not voice_config or not voice_config.get("api_key"):
        raise ValueError("未检测到语音模型 API 配置")
    base_url = voice_config.get("base_url") or "https://api.openai.com/v1"
    validate_outbound_url(base_url, allow_private=get_settings().allow_private_model_base_urls)
    return AsyncOpenAI(
        api_key=voice_config["api_key"],
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
):
    """普通文本调用的统一 fallback 入口。"""
    candidates = model_gateway.get_chat_candidates(api_config, channel)
    request_timeout = timeout or get_settings().llm_request_timeout_seconds
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        try:
            return await asyncio.wait_for(candidate.ainvoke(input_value), timeout=request_timeout)
        except Exception as exc:
            last_error = exc
            logging.getLogger(__name__).warning(
                "[LLM] 文本调用失败，切换候选: channel=%s candidate=%s error=%s",
                channel, index + 1, type(exc).__name__,
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError("没有可用的模型候选")
