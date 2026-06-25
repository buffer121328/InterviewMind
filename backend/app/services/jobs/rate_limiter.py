"""
频率限制器

保护机制：
- 单用户每小时最多 N 次采集
- 单用户每小时最多 M 次发送
- 连续失败 3 次自动暂停 30 分钟
- 内存实现（后续可切换 Redis）
"""

import logging
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


# ============================================================================
# 公开接口
# ============================================================================

async def check_rate(
    user_id: str,
    limit_type: RateLimitType,
) -> Tuple[bool, str]:
    """
    检查是否超过频率限制。
    
    Returns:
        (can_proceed: bool, message: str)
    """
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

    # 记录本次请求
    bucket.append(now)
    return True, "ok"


async def record_failure(user_id: str):
    """记录一次失败"""
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
    failure_state = _failure_states[user_id]
    failure_state["failures"] = 0
    failure_state["paused_until"] = 0


async def get_rate_status(user_id: str) -> Dict[str, Any]:
    """获取当前频率状态"""
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
