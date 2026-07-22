"""单用户 LLM 运行门禁。Redis 可用时跨 API/Worker 进程共享，否则仅本进程生效。"""

import asyncio
import contextlib
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Protocol


LOCK_KEY = "agent_interview:single_user:llm_active"
logger = logging.getLogger(__name__)


class _Lease(Protocol):
    """运行锁协议：释放锁的接口。"""

    async def release(self) -> None:
        """异步执行 `release` 相关逻辑。"""
        ...


@dataclass
class LocalLease:
    """本地进程级别的运行锁租约。"""

    lock: asyncio.Lock

    async def release(self) -> None:
        """释放本地锁。"""
        if self.lock.locked():
            self.lock.release()


class LocalRunGate:
    """本地进程级别的运行门禁（无 Redis 时回退）。"""

    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self._lock = asyncio.Lock()

    async def acquire(self) -> _Lease | None:
        """尝试获取本地锁，已被持有则返回 None。"""
        if self._lock.locked():
            return None
        await self._lock.acquire()
        return LocalLease(self._lock)


@dataclass
class RedisLease:
    """基于 Redis 的跨进程运行锁租约。"""

    client: object
    token: str
    ttl: int
    renew_task: asyncio.Task | None = None

    def start_renewal(self) -> None:
        """启动后台续租协程。"""
        self.renew_task = asyncio.create_task(self._renew_loop(), name="agent-run-lock-renewal")

    async def _renew_loop(self) -> None:
        """后台循环续租 Redis 锁，防止 TTL 过期。"""
        interval = max(1, self.ttl // 3)
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await self.client.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) end return 0",
                    1,
                    LOCK_KEY,
                    self.token,
                    self.ttl,
                )
                if not renewed:
                    logger.error("Agent 运行锁已丢失，无法继续续租")
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Agent 运行锁续租失败，将继续重试: %s", type(exc).__name__)

    async def release(self) -> None:
        """释放 Redis 锁并取消续租任务。"""
        if self.renew_task is not None:
            self.renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.renew_task
        # 只删除自己持有的锁，避免 TTL 到期后误删下一次运行的锁。
        try:
            await self.client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0",
                1,
                LOCK_KEY,
                self.token,
            )
        except Exception as exc:
            logger.warning("Agent 运行锁释放失败，等待 TTL 自动过期: %s", type(exc).__name__)


class RedisRunGate:
    """基于 Redis 的跨进程运行门禁。"""

    def __init__(self, redis_url: str) -> None:
        """初始化当前对象实例。

        Args:
            redis_url: redis URL。
        """
        from redis.asyncio import Redis

        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._ttl = int(os.getenv("AGENT_RUN_LOCK_TTL_SECONDS", "600"))

    async def acquire(self) -> _Lease | None:
        """尝试通过 Redis SET NX 获取分布式锁，失败返回 None。"""
        token = secrets.token_urlsafe(16)
        acquired = await self._client.set(LOCK_KEY, token, nx=True, ex=self._ttl)
        if not acquired:
            return None
        lease = RedisLease(self._client, token, self._ttl)
        lease.start_renewal()
        return lease


_local_gate = LocalRunGate()
_redis_gate: RedisRunGate | None = None


def get_run_gate() -> LocalRunGate | RedisRunGate:
    """同步兼容模式或未配置 Redis 时使用本地锁。"""
    global _redis_gate
    if os.getenv("TASK_QUEUE_ENABLED", "false").lower() != "true":
        return _local_gate

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError(
            "TASK_QUEUE_ENABLED=true 时必须配置 REDIS_URL"
        )
    if _redis_gate is None:
        _redis_gate = RedisRunGate(redis_url)
    return _redis_gate
