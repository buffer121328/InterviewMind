from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import logging
import os
from threading import RLock
from time import monotonic, time
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.services.observability import get_langchain_callbacks


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
    **_: Any,
) -> ChatOpenAI:
    """根据用户提供的 OpenAI-compatible 配置创建 LLM 实例。"""
    settings = get_settings()
    options = {
        "temperature": temperature,
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "model_name": model,
        "api_key": api_key,
        "base_url": base_url,
        # 由调用层负责有限重试，避免 SDK 重试与 fallback 叠加导致长时间阻塞。
        "timeout": settings.llm_request_timeout_seconds,
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


def _identity(config: dict) -> str:
    """生成不暴露 API Key 的稳定成员标识。"""
    key_fingerprint = sha256(str(config.get("api_key", "")).encode()).hexdigest()[:12]
    return "|".join((str(config.get("base_url", "")), str(config.get("model", "")), key_fingerprint))


class ModelPoolScheduler:
    """Redis 优先的全局模型池调度器；Redis 不可用时降级到进程内状态。"""

    def __init__(self, redis_client: Any = None) -> None:
        self._lock = RLock()
        self._cursor: dict[str, int] = defaultdict(int)
        self._failures: dict[str, int] = defaultdict(int)
        self._cooldown_until: dict[str, float] = {}
        self._inflight: dict[str, int] = defaultdict(int)
        self._redis = redis_client
        self._redis_checked = redis_client is not None
        self._redis_retry_after = 0.0

    @staticmethod
    def _token(value: str) -> str:
        return sha256(value.encode()).hexdigest()[:24]

    def _redis_client(self):
        if self._redis is not None:
            return self._redis
        settings = get_settings()
        if not settings.llm_pool_redis_enabled or monotonic() < self._redis_retry_after:
            return None
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return None
        try:
            from redis import Redis

            client = Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=0.3,
                socket_timeout=0.3,
            )
            client.ping()
            self._redis = client
            self._redis_checked = True
            return client
        except Exception as exc:
            if not self._redis_checked:
                logging.getLogger(__name__).warning("[ModelPool] Redis 不可用，降级为进程内调度: %s", exc)
            self._redis_checked = True
            self._redis_retry_after = monotonic() + 30
            return None

    def _redis_failed(self, exc: Exception) -> None:
        logging.getLogger(__name__).warning("[ModelPool] Redis 操作失败，临时降级: %s", exc)
        self._redis = None
        self._redis_retry_after = monotonic() + 30

    def _pool_token(self, pool_name: str, configs: list[dict]) -> str:
        signature = ",".join(sorted(_identity(item) for item in configs))
        return self._token(f"{pool_name}:{signature}")

    def _member_key(self, kind: str, identity: str) -> str:
        return f"agent_interview:model_pool:{kind}:{self._token(identity)}"

    def order(self, pool_name: str, configs: list[dict]) -> list[dict]:
        if not configs:
            return []
        redis = self._redis_client()
        members = configs
        cursor = None
        if redis is not None:
            try:
                cooldown_keys = [self._member_key("cooldown", _identity(item)) for item in configs]
                cooldowns = redis.mget(cooldown_keys)
                available = [item for item, cooling in zip(configs, cooldowns) if not cooling]
                members = available or configs
                inflight_keys = [self._member_key("inflight", _identity(item)) for item in members]
                inflights = [int(value or 0) for value in redis.mget(inflight_keys)]
                min_inflight = min(inflights)
                members = [item for item, inflight in zip(members, inflights) if inflight == min_inflight]
                pool_token = self._pool_token(pool_name, configs)
                cursor = redis.incr(f"agent_interview:model_pool:cursor:{pool_token}") - 1
            except Exception as exc:
                self._redis_failed(exc)

        with self._lock:
            if cursor is None:
                now = monotonic()
                available = [item for item in configs if self._cooldown_until.get(_identity(item), 0) <= now]
                members = available or configs
                min_inflight = min(self._inflight.get(_identity(item), 0) for item in members)
                members = [item for item in members if self._inflight.get(_identity(item), 0) == min_inflight]
            schedule: list[int] = []
            for index, config in enumerate(members):
                schedule.extend([index] * max(1, min(int(config.get("weight", 1)), 100)))
            if cursor is None:
                cursor = self._cursor[pool_name]
                self._cursor[pool_name] = cursor + 1
            cursor %= len(schedule)

            ordered: list[dict] = []
            seen: set[str] = set()
            for offset in range(len(schedule)):
                config = members[schedule[(cursor + offset) % len(schedule)]]
                identity = _identity(config)
                if identity not in seen:
                    ordered.append(config)
                    seen.add(identity)
            return ordered

    def record_success(self, identity: str) -> None:
        redis = self._redis_client()
        if redis is not None:
            try:
                redis.delete(self._member_key("failures", identity), self._member_key("cooldown", identity))
            except Exception as exc:
                self._redis_failed(exc)
        with self._lock:
            self._failures.pop(identity, None)
            self._cooldown_until.pop(identity, None)
        self.finish(identity)

    def record_failure(self, identity: str) -> None:
        settings = get_settings()
        redis = self._redis_client()
        if redis is not None:
            try:
                failure_key = self._member_key("failures", identity)
                failures = int(redis.incr(failure_key))
                redis.expire(failure_key, max(settings.llm_pool_cooldown_seconds * 2, 120))
                if failures >= settings.llm_pool_failure_threshold:
                    redis.set(
                        self._member_key("cooldown", identity),
                        str(int(time())),
                        ex=settings.llm_pool_cooldown_seconds,
                    )
                    redis.delete(failure_key)
            except Exception as exc:
                self._redis_failed(exc)
        with self._lock:
            failures = self._failures[identity] + 1
            self._failures[identity] = failures
            if failures >= settings.llm_pool_failure_threshold:
                self._cooldown_until[identity] = monotonic() + settings.llm_pool_cooldown_seconds
                self._failures[identity] = 0
        self.finish(identity)

    def start(self, identity: str) -> None:
        redis = self._redis_client()
        if redis is not None:
            try:
                key = self._member_key("inflight", identity)
                redis.incr(key)
                redis.expire(key, get_settings().llm_pool_inflight_ttl_seconds)
                return
            except Exception as exc:
                self._redis_failed(exc)
        with self._lock:
            self._inflight[identity] += 1

    def finish(self, identity: str) -> None:
        redis = self._redis_client()
        if redis is not None:
            try:
                key = self._member_key("inflight", identity)
                value = int(redis.decr(key))
                if value <= 0:
                    redis.delete(key)
                return
            except Exception as exc:
                self._redis_failed(exc)
        with self._lock:
            if self._inflight.get(identity, 0) <= 1:
                self._inflight.pop(identity, None)
            else:
                self._inflight[identity] -= 1

    def get_inflight(self, identity: str) -> int:
        redis = self._redis_client()
        if redis is not None:
            try:
                return int(redis.get(self._member_key("inflight", identity)) or 0)
            except Exception as exc:
                self._redis_failed(exc)
        with self._lock:
            return self._inflight.get(identity, 0)

    def reset(self) -> None:
        """测试和运行时重载配置时清空进程内调度状态。"""
        with self._lock:
            self._cursor.clear()
            self._failures.clear()
            self._cooldown_until.clear()
            self._inflight.clear()


class _ModelPoolCallback:
    """覆盖真实 LangChain 调用的全局健康与 in-flight 统计。"""

    def __init__(self, scheduler: ModelPoolScheduler, identity: str) -> None:
        self.scheduler = scheduler
        self.identity = identity
        self._lock = RLock()
        self._active_runs: set[str] = set()

    @staticmethod
    def _run_token(kwargs: dict[str, Any]) -> str:
        return str(kwargs.get("run_id") or "__anonymous__")

    def _start(self, kwargs: dict[str, Any]) -> None:
        token = self._run_token(kwargs)
        with self._lock:
            if token in self._active_runs:
                return
            self._active_runs.add(token)
        self.scheduler.start(self.identity)

    def _finish(self, kwargs: dict[str, Any], *, success: bool) -> None:
        token = self._run_token(kwargs)
        with self._lock:
            if token not in self._active_runs:
                return
            self._active_runs.remove(token)
        if success:
            self.scheduler.record_success(self.identity)
        else:
            self.scheduler.record_failure(self.identity)

    def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        self._start(kwargs)

    def on_llm_start(self, *args: Any, **kwargs: Any) -> None:
        self._start(kwargs)

    def on_llm_end(self, *args: Any, **kwargs: Any) -> None:
        self._finish(kwargs, success=True)

    def on_llm_error(self, *args: Any, **kwargs: Any) -> None:
        self._finish(kwargs, success=False)


class ModelGateway:
    """模型网关：Redis 全局调度优先，通道回退与进程内降级。"""

    def __init__(self) -> None:
        self.scheduler = ModelPoolScheduler()
        self._candidate_identities: dict[int, str] = {}
        self._candidate_lock = RLock()

    def _bind_identity(self, llm: object, identity: str) -> None:
        try:
            object.__setattr__(llm, "_model_pool_identity", identity)
        except Exception:
            with self._candidate_lock:
                self._candidate_identities[id(llm)] = identity

    def _take_identity(self, llm: object) -> str | None:
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
        configured = [dict(item) for item in api_config.get(name, []) if item and item.get("api_key")]
        if configured:
            return configured
        fallback = api_config.get(fallback_channel)
        return [dict(fallback)] if fallback and fallback.get("api_key") else []

    def _candidate_configs(self, api_config: dict, channel: str) -> list[dict]:
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
        for pool_name, configs in groups:
            for config in self.scheduler.order(pool_name, configs):
                identity = _identity(config)
                if identity not in seen:
                    ordered.append(config)
                    seen.add(identity)
        return ordered

    def get_chat_candidates(self, api_config: Optional[dict], channel: str = "smart") -> list[ChatOpenAI]:
        if not api_config:
            raise ValueError("未检测到 API 配置。请在设置中配置您的大模型 API 后再使用本功能。")
        configs = self._candidate_configs(api_config, channel)
        if not configs:
            configs = [_resolve_channel_config(api_config, channel)]

        candidates: list[ChatOpenAI] = []
        for config in configs:
            llm = create_llm_from_config(
                api_key=config["api_key"],
                base_url=config["base_url"],
                model=config["model"],
                max_tokens=get_settings().llm_max_tokens,
                extra_callbacks=[_ModelPoolCallback(self.scheduler, _identity(config))],
            )
            self._bind_identity(llm, _identity(config))
            candidates.append(llm)
        return candidates

    def get_chat_model(self, api_config: Optional[dict], channel: str = "smart") -> ChatOpenAI:
        return self.get_chat_candidates(api_config, channel)[0]

    def record_chat_success(self, llm: object) -> None:
        identity = self._take_identity(llm)
        if identity and not getattr(llm, "_model_pool_callback_managed", False):
            self.scheduler.record_success(identity)

    def record_chat_failure(self, llm: object) -> None:
        identity = self._take_identity(llm)
        if identity and not getattr(llm, "_model_pool_callback_managed", False):
            self.scheduler.record_failure(identity)

    def get_voice_client(self, api_config: dict):
        voice_config = _resolve_channel_config(api_config, "voice")
        return get_async_omni_client(voice_config)

    def get_voice_request_options(self, api_config: dict) -> dict:
        settings = get_settings()
        voice_config = api_config.get("voice") or {}
        return {
            "model": voice_config.get("model") or settings.voice_model,
            "modalities": ["text", "audio"],
            "audio": {"voice": settings.voice_name, "format": settings.voice_output_format},
        }

    def get_voice_input_format(self) -> str:
        return get_settings().voice_input_format


model_gateway = ModelGateway()


def get_llm_candidates_for_request(api_config: Optional[dict] = None, channel: str = "smart") -> list[ChatOpenAI]:
    """兼容旧调用入口，候选顺序由模型网关统一调度。"""
    return model_gateway.get_chat_candidates(api_config, channel)


def get_llm_for_request(api_config: Optional[dict] = None, channel: str = "smart") -> ChatOpenAI:
    import logging

    logging.getLogger(__name__).info("[LLM] 请求通道: %s", channel)
    return model_gateway.get_chat_model(api_config, channel)


def get_async_omni_client(voice_config: dict):
    """根据前端传入的配置创建异步 OpenAI 客户端。"""
    from openai import AsyncOpenAI

    if not voice_config or not voice_config.get("api_key"):
        raise ValueError("未检测到语音模型 API 配置")
    return AsyncOpenAI(api_key=voice_config["api_key"], base_url=voice_config["base_url"])
