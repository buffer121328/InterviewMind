"""Model-pool scheduling and LangChain callback integration."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import logging
import os
from threading import RLock
from time import monotonic, time
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler

from app.config import get_settings


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

    def reserve_order(self, pool_name: str, configs: list[dict]) -> tuple[list[dict], str | None]:
        """原子选择并预占首候选；Redis 不可用时保持旧的进程内排序。"""
        if not configs:
            return [], None
        redis = self._redis_client()
        if redis is None or not hasattr(redis, "pipeline"):
            return self.order(pool_name, configs), None

        cooldown_keys = [self._member_key("cooldown", _identity(item)) for item in configs]
        inflight_keys = [self._member_key("inflight", _identity(item)) for item in configs]
        cursor_key = f"agent_interview:model_pool:cursor:{self._pool_token(pool_name, configs)}"
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
                pipe.multi()
                pipe.incr(cursor_key)
                pipe.incr(selected_key)
                pipe.expire(selected_key, get_settings().llm_pool_inflight_ttl_seconds)
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


class _ModelPoolCallback(BaseCallbackHandler):
    """覆盖真实 LangChain 调用的全局健康与 in-flight 统计。"""

    def __init__(self, scheduler: ModelPoolScheduler, identity: str, *, pre_reserved: bool = False) -> None:
        self.scheduler = scheduler
        self.identity = identity
        self._lock = RLock()
        self._active_runs: set[str] = set()
        self._pre_reserved = pre_reserved

    @staticmethod
    def _run_token(kwargs: dict[str, Any]) -> str:
        return str(kwargs.get("run_id") or "__anonymous__")

    def _start(self, kwargs: dict[str, Any]) -> None:
        token = self._run_token(kwargs)
        with self._lock:
            if token in self._active_runs:
                return
            self._active_runs.add(token)
            pre_reserved = self._pre_reserved
            self._pre_reserved = False
        if not pre_reserved:
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
