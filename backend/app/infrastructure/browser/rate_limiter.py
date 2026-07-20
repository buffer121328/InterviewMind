"""
频率限制器

保护机制：
- 单用户每小时最多 N 次采集
- 单用户每小时最多 M 次发送
- 连续失败 3 次自动暂停 30 分钟
- 配置 REDIS_URL 时跨进程持久化；本地开发回退内存实现
"""

import hashlib
import logging
import os
import secrets
import time
from enum import Enum
from typing import Dict, Any, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class RateLimitType(str, Enum):
    CAPTURE = "capture"  # 岗位采集
    SEND = "send"        # 投递发送


# ============================================================================
# 配置
# ============================================================================

RATE_LIMITS = {
    RateLimitType.CAPTURE: {
        "max_per_hour": 30,     # 每小时最多采集30次
        "window_seconds": 3600,
    },
    RateLimitType.SEND: {
        "max_per_hour": 10,     # 每小时最多发送10次
        "window_seconds": 3600,
    },
}

# 连续失败配置
MAX_CONSECUTIVE_FAILURES = 3
FAILURE_COOLDOWN_SECONDS = 1800  # 30分钟


# ============================================================================
# 内存存储
# ============================================================================

# {user_id: {RateLimitType: [timestamp, ...]}}
_rate_buckets: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))

# {user_id: {"failures": int, "paused_until": float}}
_failure_states: Dict[str, Dict[str, Any]] = defaultdict(
    lambda: {"failures": 0, "paused_until": 0}
)


class RedisRateLimitStore:
    """使用 Redis Lua 原子执行滑动窗口与失败熔断。"""

    _CHECK_SCRIPT = """
    local paused_until = tonumber(redis.call('HGET', KEYS[2], 'paused_until') or '0')
    if paused_until > tonumber(ARGV[1]) then
        return {-1, paused_until - tonumber(ARGV[1])}
    end
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]) - tonumber(ARGV[2]))
    local used = redis.call('ZCARD', KEYS[1])
    if used >= tonumber(ARGV[3]) then return {0, used} end
    if ARGV[4] == '1' then
        redis.call('ZADD', KEYS[1], ARGV[1], ARGV[5])
        redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[2]) / 1000) + 60)
        used = used + 1
    end
    return {1, used}
    """
    _FAILURE_SCRIPT = """
    local failures = redis.call('HINCRBY', KEYS[1], 'failures', 1)
    if failures >= tonumber(ARGV[2]) then
        redis.call('HSET', KEYS[1], 'paused_until', tonumber(ARGV[1]) + tonumber(ARGV[3]))
    end
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
    return failures
    """

    def __init__(self, redis_url: str) -> None:
        from redis.asyncio import Redis

        self._client = Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _user_key(user_id: str) -> str:
        return hashlib.sha256(user_id.encode()).hexdigest()

    def _rate_key(self, user_id: str, limit_type: RateLimitType) -> str:
        return f"agent-interview:rate:{self._user_key(user_id)}:{limit_type.value}"

    def _failure_key(self, user_id: str) -> str:
        return f"agent-interview:rate:{self._user_key(user_id)}:failures"

    async def check_rate(
        self, user_id: str, limit_type: RateLimitType, *, record: bool
    ) -> Tuple[bool, str]:
        config = RATE_LIMITS[limit_type]
        now_ms = int(time.time() * 1000)
        result = await self._client.eval(
            self._CHECK_SCRIPT,
            2,
            self._rate_key(user_id, limit_type),
            self._failure_key(user_id),
            now_ms,
            int(config["window_seconds"] * 1000),
            config["max_per_hour"],
            "1" if record else "0",
            f"{now_ms}:{secrets.token_hex(8)}",
        )
        code, value = int(result[0]), int(result[1])
        if code == -1:
            return False, f"由于连续失败，操作已暂停 {max(1, value // 1000)} 秒，请稍后再试"
        if code == 0:
            return False, (
                f"频率限制：{limit_type.value} 每小时最多 "
                f"{config['max_per_hour']} 次，请稍后再试"
            )
        return True, "ok"

    async def record_failure(self, user_id: str) -> None:
        await self._client.eval(
            self._FAILURE_SCRIPT,
            1,
            self._failure_key(user_id),
            int(time.time() * 1000),
            MAX_CONSECUTIVE_FAILURES,
            FAILURE_COOLDOWN_SECONDS * 1000,
            max(FAILURE_COOLDOWN_SECONDS * 2, 3600),
        )

    async def record_success(self, user_id: str) -> None:
        await self._client.delete(self._failure_key(user_id))

    async def get_rate_status(self, user_id: str) -> Dict[str, Any]:
        now = time.time()
        status: Dict[str, Any] = {}
        for limit_type in RateLimitType:
            config = RATE_LIMITS[limit_type]
            key = self._rate_key(user_id, limit_type)
            await self._client.zremrangebyscore(
                key, "-inf", int((now - config["window_seconds"]) * 1000)
            )
            used = int(await self._client.zcard(key))
            status[limit_type.value] = {
                "used": used,
                "limit": config["max_per_hour"],
                "remaining": max(0, config["max_per_hour"] - used),
            }
        failure = await self._client.hgetall(self._failure_key(user_id))
        paused_until = float(failure.get("paused_until", 0)) / 1000
        status["failures"] = int(failure.get("failures", 0))
        status["paused"] = now < paused_until
        if status["paused"]:
            status["paused_remaining"] = int(paused_until - now)
        return status


def _build_redis_store() -> RedisRateLimitStore | None:
    redis_url = os.getenv("REDIS_URL")
    return RedisRateLimitStore(redis_url) if redis_url else None


_redis_store = _build_redis_store()


# ============================================================================
# 公开接口
# ============================================================================

async def check_rate(
    user_id: str,
    limit_type: RateLimitType,
    *,
    record: bool = True,
) -> Tuple[bool, str]:
    """
    检查是否超过频率限制。
    
    Returns:
        (can_proceed: bool, message: str)
    """
    if _redis_store:
        try:
            return await _redis_store.check_rate(user_id, limit_type, record=record)
        except Exception:
            logger.exception("[RateLimiter] Redis 检查失败，已拒绝外部操作")
            return False, "限流服务暂不可用，操作已安全暂停"

    now = time.time()

    # 检查是否在冷却期
    failure_state = _failure_states[user_id]
    if now < failure_state["paused_until"]:
        remaining = int(failure_state["paused_until"] - now)
        return False, f"由于连续失败，操作已暂停 {remaining} 秒，请稍后再试"

    # 清理过期记录
    limit_config = RATE_LIMITS[limit_type]
    window = limit_config["window_seconds"]
    bucket = _rate_buckets[user_id][limit_type.value]
    bucket[:] = [t for t in bucket if now - t < window]

    # 检查是否超限
    if len(bucket) >= limit_config["max_per_hour"]:
        return False, (
            f"频率限制：{limit_type.value} 每小时最多 "
            f"{limit_config['max_per_hour']} 次，请稍后再试"
        )

    if record:
        bucket.append(now)
    return True, "ok"


async def record_failure(user_id: str):
    """记录一次失败"""
    if _redis_store:
        await _redis_store.record_failure(user_id)
        return
    failure_state = _failure_states[user_id]
    failure_state["failures"] += 1

    logger.warning(
        f"[RateLimiter] 用户 {user_id} 连续失败 {failure_state['failures']} 次"
    )

    if failure_state["failures"] >= MAX_CONSECUTIVE_FAILURES:
        failure_state["paused_until"] = time.time() + FAILURE_COOLDOWN_SECONDS
        logger.warning(
            f"[RateLimiter] 用户 {user_id} 已自动暂停 {FAILURE_COOLDOWN_SECONDS} 秒"
        )


async def record_success(user_id: str):
    """记录一次成功（重置失败计数）"""
    if _redis_store:
        await _redis_store.record_success(user_id)
        return
    failure_state = _failure_states[user_id]
    failure_state["failures"] = 0
    failure_state["paused_until"] = 0


async def get_rate_status(user_id: str) -> Dict[str, Any]:
    """获取当前频率状态"""
    if _redis_store:
        return await _redis_store.get_rate_status(user_id)
    now = time.time()
    status = {}

    for limit_type in RateLimitType:
        bucket = _rate_buckets[user_id][limit_type.value]
        bucket[:] = [t for t in bucket if now - t < RATE_LIMITS[limit_type]["window_seconds"]]

        status[limit_type.value] = {
            "used": len(bucket),
            "limit": RATE_LIMITS[limit_type]["max_per_hour"],
            "remaining": max(0, RATE_LIMITS[limit_type]["max_per_hour"] - len(bucket)),
        }

    failure_state = _failure_states[user_id]
    status["failures"] = failure_state["failures"]
    status["paused"] = now < failure_state["paused_until"]
    if status["paused"]:
        status["paused_remaining"] = int(failure_state["paused_until"] - now)

    return status
