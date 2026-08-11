"""提供模型相关后端功能。"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from hashlib import sha256
from threading import RLock
from time import monotonic, time
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler

from ai.runtime.error_classification import classify_exception
from app.config import get_settings
from app.redis_keys import build_redis_key
from observability import (
    estimate_model_cost,
    extract_token_usage,
    get_current_model_call_metadata,
    measure_model_input,
    record_model_event,
)


def _identity(config: dict) -> str:
    """生成不暴露 API Key 的稳定成员标识。"""
    key_fingerprint = sha256(str(config.get("api_key", "")).encode()).hexdigest()[:12]
    return "|".join((
        str(config.get("provider", "")),
        str(config.get("integration", "")),
        str(config.get("base_url", "")),
        str(config.get("model", "")),
        key_fingerprint,
    ))


class ModelPoolScheduler:
    """Redis 优先的全局模型池调度器；Redis 不可用时降级到进程内状态。"""

    def __init__(self, redis_client: Any = None) -> None:
        """初始化模型池调度状态；优先使用调用方提供的 Redis 客户端，否则按配置懒加载。"""
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
        """将内部池标识哈希为固定长度 token，避免把模型配置原文写入 Redis key。"""
        return sha256(value.encode()).hexdigest()[:24]

    def _redis_client(self):
        """获取可用 Redis 客户端；连接失败时短暂冷却重试并降级到进程内调度。"""
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
                logging.getLogger(__name__).warning(
                    "[ModelPool] Redis 不可用，降级为进程内调度: error_type=%s",
                    type(exc).__name__,
                )
            self._redis_checked = True
            self._redis_retry_after = monotonic() + 30
            return None

    def _redis_failed(self, exc: Exception) -> None:
        """记录 Redis 操作失败并设置临时降级窗口，避免每次模型调用都阻塞在不可用的外部依赖上。"""
        logging.getLogger(__name__).warning(
            "[ModelPool] Redis 操作失败，临时降级: error_type=%s",
            type(exc).__name__,
        )
        self._redis = None
        self._redis_retry_after = monotonic() + 30

    def _pool_token(self, pool_name: str, configs: list[dict]) -> str:
        """根据池名称和成员指纹生成跨进程一致的调度游标标识。"""
        signature = ",".join(sorted(_identity(item) for item in configs))
        return self._token(f"{pool_name}:{signature}")

    def _cursor_key(self, pool_name: str, configs: list[dict]) -> str:
        """生成不含明文池配置的 Redis 轮询游标 key。"""
        return build_redis_key("model_pool", "cursor", self._pool_token(pool_name, configs))

    def _member_key(self, kind: str, identity: str) -> str:
        """生成不含明文模型配置的 Redis 成员状态 key。"""
        return build_redis_key("model_pool", kind, self._token(identity))

    def order(self, pool_name: str, configs: list[dict]) -> list[dict]:
        """按冷却状态、in-flight 数量和轮询游标排列模型配置，确保故障模型被隔离且请求尽量均衡。"""
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
                cursor_key = self._cursor_key(pool_name, configs)
                cursor = int(redis.eval(
                    "local value = redis.call('INCR', KEYS[1]); "
                    "redis.call('EXPIRE', KEYS[1], ARGV[1]); return value",
                    1,
                    cursor_key,
                    get_settings().llm_pool_cursor_ttl_seconds,
                )) - 1
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

    def reserve_order(self, pool_name: str, configs: list[dict]) -> tuple[list[dict], str | None]:
        """原子选择并预占首候选；Redis 不可用时切换到进程内安全调度。"""
        if not configs:
            return [], None
        redis = self._redis_client()
        if redis is None or not hasattr(redis, "pipeline"):
            return self.order(pool_name, configs), None

        cooldown_keys = [self._member_key("cooldown", _identity(item)) for item in configs]
        inflight_keys = [self._member_key("inflight", _identity(item)) for item in configs]
        cursor_key = self._cursor_key(pool_name, configs)
        try:
            from redis.exceptions import WatchError
        except Exception:
            WatchError = RuntimeError

        for _attempt in range(5):
            pipe = redis.pipeline()
            try:
                pipe.watch(cursor_key, *cooldown_keys, *inflight_keys)
                cooldowns = pipe.mget(cooldown_keys)
                available_pairs = [(item, key) for item, key, cooling in zip(configs, inflight_keys, cooldowns) if not cooling]
                candidate_pairs = available_pairs or list(zip(configs, inflight_keys))
                inflights = [int(value or 0) for value in pipe.mget([key for _item, key in candidate_pairs])]
                min_inflight = min(inflights)
                members = [item for (item, _key), value in zip(candidate_pairs, inflights) if value == min_inflight]
                schedule: list[int] = []
                for index, config in enumerate(members):
                    schedule.extend([index] * max(1, min(int(config.get("weight", 1)), 100)))
                cursor = int(pipe.get(cursor_key) or 0)
                cursor %= len(schedule)
                ordered: list[dict] = []
                seen: set[str] = set()
                for offset in range(len(schedule)):
                    config = members[schedule[(cursor + offset) % len(schedule)]]
                    identity = _identity(config)
                    if identity not in seen:
                        ordered.append(config)
                        seen.add(identity)
                selected_identity = _identity(ordered[0])
                selected_key = self._member_key("inflight", selected_identity)
                settings = get_settings()
                pipe.multi()
                pipe.incr(cursor_key)
                pipe.expire(cursor_key, settings.llm_pool_cursor_ttl_seconds)
                pipe.incr(selected_key)
                pipe.expire(selected_key, settings.llm_pool_inflight_ttl_seconds)
                pipe.execute()
                return ordered, selected_identity
            except WatchError:
                continue
            except Exception as exc:
                self._redis_failed(exc)
                break
            finally:
                try:
                    pipe.reset()
                except Exception:
                    pass
        return self.order(pool_name, configs), None

    def record_success(self, identity: str) -> None:
        """记录一次成功调用并清除该模型的失败/冷却状态，同时释放 in-flight 计数。"""
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
        """记录模型调用失败；达到阈值后进入冷却，避免持续把请求发送到不健康成员。"""
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
        """增加模型成员的 in-flight 计数，用于并发调度；Redis 失败时使用进程内计数。"""
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
        """释放模型成员的 in-flight 计数，并清理归零的状态键。"""
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
        """读取模型成员当前并发数；读取失败时返回本地降级计数而不是阻断调用。"""
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


class _ModelPoolCallback(BaseCallbackHandler):
    """统一记录 LangChain 调用体积、耗时、失败类型和模型池健康状态。"""

    def __init__(
        self,
        scheduler: ModelPoolScheduler,
        identity: str,
        *,
        pre_reserved: bool = False,
        channel: str | None = None,
        model_name: str | None = None,
        provider_metadata: dict[str, Any] | None = None,
        candidate_count: int = 1,
        candidate_index: int = 1,
        output_token_limit: int | None = None,
    ) -> None:
        """初始化模型池与安全观测字段；不会保存 prompt、消息正文或凭据。"""
        self.scheduler = scheduler
        self.identity = identity
        self.channel = channel
        self.model_name = model_name
        self.provider_metadata = dict(provider_metadata or {})
        self.candidate_count = max(1, candidate_count)
        self.candidate_index = max(1, candidate_index)
        self.output_token_limit = output_token_limit
        self._lock = RLock()
        self._active_runs: set[str] = set()
        self._run_metrics: dict[str, tuple[float, dict[str, Any]]] = {}
        self._pre_reserved = pre_reserved

    @staticmethod
    def _run_token(kwargs: dict[str, Any]) -> str:
        """从 LangChain 回调参数提取一次运行的稳定标识，防止同一调用被重复计数。"""
        return str(kwargs.get("run_id") or "__anonymous__")

    def _event_base(self) -> dict[str, Any]:
        """返回不含业务原文的固定模型成员与候选信息。"""
        return {
            "channel": self.channel,
            "model_name": self.model_name,
            **self.provider_metadata,
            "model_member": sha256(self.identity.encode("utf-8")).hexdigest()[:16],
            "candidate_count": self.candidate_count,
            "candidate_index": self.candidate_index,
            "fallback_index": self.candidate_index - 1,
            "output_token_limit": self.output_token_limit,
        }

    def _start(self, kwargs: dict[str, Any], input_value: Any = None) -> None:
        """登记模型运行，并只记录输入体积、来源计数和 deadline 元数据。"""
        token = self._run_token(kwargs)
        with self._lock:
            if token in self._active_runs:
                return
            self._active_runs.add(token)
            metrics = measure_model_input(
                input_value,
                chars_per_token=get_settings().llm_estimated_chars_per_token,
            )
            metadata = get_current_model_call_metadata()
            self._run_metrics[token] = (monotonic(), {**metrics, **metadata})
            pre_reserved = self._pre_reserved
            self._pre_reserved = False
        if not pre_reserved:
            self.scheduler.start(self.identity)
        record_model_event(**{
            **self._event_base(),
            **metrics,
            **metadata,
            "event_type": "llm.request.started",
        })

    @staticmethod
    def _has_non_empty_text(token: Any, chunk: Any = None) -> bool:
        """Return whether a streaming callback carries visible text without retaining it."""

        if isinstance(token, str) and token.strip():
            return True
        content = getattr(chunk, "content", None)
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, (list, tuple)):
            for item in content:
                if isinstance(item, str) and item.strip():
                    return True
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str) and text.strip():
                        return True
        return False

    def _record_first_chunk(self, kwargs: dict[str, Any], *, token: Any, chunk: Any = None) -> None:
        """Store only the first non-empty chunk latency for one active model run."""

        if not self._has_non_empty_text(token, chunk):
            return
        run_token = self._run_token(kwargs)
        with self._lock:
            metrics_entry = self._run_metrics.get(run_token)
            if run_token not in self._active_runs or metrics_entry is None:
                return
            started_at, metrics = metrics_entry
            if "first_chunk_duration_ms" in metrics:
                return
            metrics["first_chunk_duration_ms"] = max(0, int((monotonic() - started_at) * 1000))

    def _finish(
        self,
        kwargs: dict[str, Any],
        *,
        success: bool,
        response: Any = None,
        error: BaseException | None = None,
    ) -> None:
        """结束模型运行，记录耗时/token/失败分类并释放模型池 in-flight。"""
        token = self._run_token(kwargs)
        with self._lock:
            if token not in self._active_runs:
                return
            self._active_runs.remove(token)
            started_at, metrics = self._run_metrics.pop(token, (monotonic(), {}))
        if success:
            self.scheduler.record_success(self.identity)
        else:
            self.scheduler.record_failure(self.identity)
        model_duration_ms = max(0, int((monotonic() - started_at) * 1000))
        queue_wait_ms = int(metrics.get("queue_wait_ms") or 0)
        event = {
            **self._event_base(),
            **metrics,
            "event_type": "llm.request.completed" if success else "llm.request.failed",
            "model_duration_ms": model_duration_ms,
            "duration_ms": model_duration_ms,
            "total_duration_ms": model_duration_ms + max(0, queue_wait_ms),
        }
        if success:
            usage = extract_token_usage(response)
            event.update(usage)
            event.update(estimate_model_cost(
                pricing_key=self.provider_metadata.get("pricing_key"),
                model_name=self.model_name,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            ))
        elif error is not None:
            classified = classify_exception(error)
            event.update(
                error_type=type(error).__name__,
                error_category=classified.category.value,
                error_code=classified.code,
                failure_type=classified.failure_type.value,
            )
        if success or not metrics.get("wrapper_managed"):
            record_model_event(**event)

    def on_chat_model_start(
        self,
        serialized: Any = None,
        messages: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """接收聊天模型开始事件；只统计消息长度，不保存消息内容。"""
        self._start(kwargs, messages)

    def on_llm_start(
        self,
        serialized: Any = None,
        prompts: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """接收传统 LLM 开始事件；只统计 prompt 长度，不保存 prompt。"""
        self._start(kwargs, prompts)

    def on_llm_new_token(
        self,
        token: str,
        *args: Any,
        chunk: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record elapsed time to the first non-empty streamed text chunk only."""

        self._record_first_chunk(kwargs, token=token, chunk=chunk)

    def on_llm_end(self, response: Any = None, *args: Any, **kwargs: Any) -> None:
        """接收模型成功事件，记录 token/耗时并释放并发计数。"""
        self._finish(kwargs, success=True, response=response)

    def on_llm_error(self, error: BaseException | None = None, *args: Any, **kwargs: Any) -> None:
        """接收模型失败事件，记录稳定失败类型并释放并发计数。"""
        self._finish(kwargs, success=False, error=error)
