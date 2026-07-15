"""单用户 LLM 运行门禁。Redis 可用时跨 API/Worker 进程共享，否则仅本进程生效。"""

import asyncio
import os
import secrets
from dataclasses import dataclass
from typing import Protocol


LOCK_KEY = "agent_interview:single_user:llm_active"


class _Lease(Protocol):
    async def release(self) -> None: ...


@dataclass
class LocalLease:
    lock: asyncio.Lock

    async def release(self) -> None:
        if self.lock.locked():
            self.lock.release()


class LocalRunGate:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def acquire(self) -> _Lease | None:
        if self._lock.locked():
            return None
        await self._lock.acquire()
        return LocalLease(self._lock)


@dataclass
class RedisLease:
    client: object
    token: str

    async def release(self) -> None:
        # 只删除自己持有的锁，避免 TTL 到期后误删下一次运行的锁。
        await self.client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0",
            1,
            LOCK_KEY,
            self.token,
        )


class RedisRunGate:
    def __init__(self, redis_url: str) -> None:
        from redis.asyncio import Redis

        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._ttl = int(os.getenv("AGENT_RUN_LOCK_TTL_SECONDS", "600"))

    async def acquire(self) -> _Lease | None:
        token = secrets.token_urlsafe(16)
        acquired = await self._client.set(LOCK_KEY, token, nx=True, ex=self._ttl)
        return RedisLease(self._client, token) if acquired else None


_local_gate = LocalRunGate()
_redis_gate: RedisRunGate | None = None


def get_run_gate() -> LocalRunGate | RedisRunGate:
    """同步兼容模式或未配置 Redis 时使用本地锁。"""
    global _redis_gate
    if os.getenv("TASK_QUEUE_ENABLED", "false").lower() != "true":
        return _local_gate

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return _local_gate
    if _redis_gate is None:
        _redis_gate = RedisRunGate(redis_url)
    return _redis_gate
