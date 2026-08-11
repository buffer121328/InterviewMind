"""提供保留相关后端功能。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.redis_keys import build_redis_key

SECONDS_PER_DAY = 24 * 60 * 60
SECONDS_PER_HOUR = 60 * 60


class CleanupAction(StrEnum):
    """定义保留相关后端数据结构或服务组件。"""

    KEEP = "KEEP"
    MARK = "MARK"
    DELETE = "DELETE"


@dataclass(frozen=True, slots=True)
class RetentionState:
    """定义保留状态相关后端数据结构或服务组件。"""

    access_count: int = 0
    last_accessed_at: datetime | None = None
    candidate_since: datetime | None = None


@dataclass(frozen=True, slots=True)
class CleanupDecision:
    """定义决策相关后端数据结构或服务组件。"""

    memory_id: str
    action: CleanupAction
    retention_class: str
    reason: str
    candidate_since: datetime | None = None


class MemoryRetentionStore:
    """定义记忆保留存储相关后端数据结构或服务组件。"""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    @staticmethod
    def _owner_hash(user_id: str) -> str:
        return hashlib.sha256(user_id.encode()).hexdigest()

    @classmethod
    def _access_key(cls, user_id: str, memory_id: str) -> str:
        return build_redis_key("memory_retention", "access", cls._owner_hash(user_id), memory_id)

    @classmethod
    def _candidate_key(cls, user_id: str, memory_id: str) -> str:
        return build_redis_key("memory_retention", "candidate", cls._owner_hash(user_id), memory_id)

    @classmethod
    def _sweep_key(cls, user_id: str) -> str:
        return build_redis_key("memory_retention", "sweep", cls._owner_hash(user_id))

    async def record_access(self, user_id: str, memory_ids: list[str]) -> bool:
        """记录保留相关后端逻辑。"""

        unique_ids = list(dict.fromkeys(memory_id for memory_id in memory_ids if memory_id))
        if not unique_ids:
            return True
        now = datetime.now(UTC).isoformat()
        access_ttl_seconds = get_settings().memory_retention_state_ttl_days * SECONDS_PER_DAY
        try:
            pipeline = self._redis.pipeline(transaction=False)
            for memory_id in unique_ids:
                access_key = self._access_key(user_id, memory_id)
                pipeline.hincrby(access_key, "access_count", 1)
                pipeline.hset(access_key, mapping={"last_accessed_at": now})
                pipeline.expire(access_key, access_ttl_seconds)
                pipeline.delete(self._candidate_key(user_id, memory_id))
            await pipeline.execute()
            return True
        except RedisError:
            return False

    async def load_states(
        self,
        user_id: str,
        memory_ids: list[str],
    ) -> dict[str, RetentionState] | None:
        """加载状态相关后端逻辑。"""

        if not memory_ids:
            return {}
        try:
            pipeline = self._redis.pipeline(transaction=False)
            for memory_id in memory_ids:
                pipeline.hgetall(self._access_key(user_id, memory_id))
                pipeline.get(self._candidate_key(user_id, memory_id))
            values = await pipeline.execute()
        except RedisError:
            # 说明：Cleanup must fail closed when Redis cannot prove recent access or
            # 说明：the beginning of a grace period.
            return None

        states: dict[str, RetentionState] = {}
        for index, memory_id in enumerate(memory_ids):
            raw_access = values[index * 2] or {}
            raw_candidate = values[index * 2 + 1]
            decoded = {
                (key.decode() if isinstance(key, bytes) else str(key)):
                (value.decode() if isinstance(value, bytes) else str(value))
                for key, value in raw_access.items()
            }
            candidate_text = (
                raw_candidate.decode() if isinstance(raw_candidate, bytes) else raw_candidate
            )
            states[memory_id] = RetentionState(
                access_count=_safe_int(decoded.get("access_count")),
                last_accessed_at=_parse_datetime(decoded.get("last_accessed_at")),
                candidate_since=_parse_datetime(candidate_text),
            )
        return states

    async def mark_candidates(self, user_id: str, memory_ids: list[str]) -> int:
        """标记候选项相关后端逻辑。"""

        if not memory_ids:
            return 0
        now = datetime.now(UTC).isoformat()
        access_ttl_seconds = get_settings().memory_retention_state_ttl_days * SECONDS_PER_DAY
        try:
            pipeline = self._redis.pipeline(transaction=False)
            for memory_id in memory_ids:
                pipeline.set(
                    self._candidate_key(user_id, memory_id),
                    now,
                    ex=access_ttl_seconds,
                    nx=True,
                )
            return sum(bool(value) for value in await pipeline.execute())
        except RedisError:
            return 0

    async def clear(self, user_id: str, memory_ids: list[str]) -> None:
        """清理保留相关后端逻辑。"""

        keys = [
            key
            for memory_id in memory_ids
            for key in (
                self._access_key(user_id, memory_id),
                self._candidate_key(user_id, memory_id),
            )
        ]
        if not keys:
            return
        try:
            await self._redis.delete(*keys)
        except RedisError:
            return

    async def cancel_candidates(self, user_id: str, memory_ids: list[str]) -> None:
        """取消候选项相关后端逻辑。"""

        keys = [
            self._candidate_key(user_id, memory_id)
            for memory_id in dict.fromkeys(memory_ids)
            if memory_id
        ]
        if not keys:
            return
        try:
            await self._redis.delete(*keys)
        except RedisError:
            return

    async def acquire_daily_sweep(self, user_id: str) -> bool:
        """处理保留相关后端逻辑。"""

        cleanup_interval_seconds = (
            get_settings().memory_retention_cleanup_interval_hours * SECONDS_PER_HOUR
        )
        try:
            return bool(await self._redis.set(
                self._sweep_key(user_id),
                datetime.now(UTC).isoformat(),
                ex=cleanup_interval_seconds,
                nx=True,
            ))
        except RedisError:
            return False


def plan_cleanup(
    records: list[dict[str, Any]],
    states: dict[str, RetentionState],
    *,
    now: datetime | None = None,
) -> list[CleanupDecision]:
    """处理计划清理相关后端逻辑。"""

    current = now or datetime.now(UTC)
    settings = get_settings()
    durable_min_age_days = settings.memory_retention_durable_min_age_days
    durable_inactive_days = settings.memory_retention_durable_inactive_days
    transient_min_age_days = settings.memory_retention_transient_min_age_days
    transient_inactive_days = settings.memory_retention_transient_inactive_days
    cleanup_grace_days = settings.memory_retention_cleanup_grace_days
    decisions: list[CleanupDecision] = []
    for record in records:
        memory_id = record.get("id")
        if not isinstance(memory_id, str):
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        retention_class = str(metadata.get("retention_class") or "core").lower()
        if metadata.get("source") == "manual" or retention_class not in {"durable", "transient"}:
            decisions.append(CleanupDecision(
                memory_id=memory_id,
                action=CleanupAction.KEEP,
                retention_class="core" if retention_class not in {"durable", "transient"} else retention_class,
                reason="protected core or unclassified legacy memory",
            ))
            continue

        state = states.get(memory_id, RetentionState())
        confirmed_at = _latest_datetime(
            _parse_datetime(metadata.get("last_confirmed_at")),
            _parse_datetime(record.get("updated_at")),
            _parse_datetime(record.get("created_at")),
        ) or current
        last_signal = _latest_datetime(confirmed_at, state.last_accessed_at) or confirmed_at
        age_days = max(0, (current - confirmed_at).days)
        inactive_days = max(0, (current - last_signal).days)
        if retention_class == "durable":
            eligible = age_days >= durable_min_age_days and inactive_days >= durable_inactive_days
            threshold_reason = (
                f"durable memory age={age_days}d inactive={inactive_days}d"
            )
        else:
            eligible = age_days >= transient_min_age_days and inactive_days >= transient_inactive_days
            threshold_reason = (
                f"transient memory age={age_days}d inactive={inactive_days}d"
            )

        if not eligible:
            decisions.append(CleanupDecision(
                memory_id=memory_id,
                action=CleanupAction.KEEP,
                retention_class=retention_class,
                reason="retention or inactivity threshold not reached",
                candidate_since=state.candidate_since,
            ))
            continue
        if state.candidate_since is None:
            decisions.append(CleanupDecision(
                memory_id=memory_id,
                action=CleanupAction.MARK,
                retention_class=retention_class,
                reason=f"{threshold_reason}; start {cleanup_grace_days}d grace period",
            ))
            continue
        grace_days = max(0, (current - state.candidate_since).days)
        action = CleanupAction.DELETE if grace_days >= cleanup_grace_days else CleanupAction.KEEP
        decisions.append(CleanupDecision(
            memory_id=memory_id,
            action=action,
            retention_class=retention_class,
            reason=(
                f"cleanup grace completed after {grace_days}d"
                if action is CleanupAction.DELETE
                else f"cleanup grace active for {grace_days}/{cleanup_grace_days}d"
            ),
            candidate_since=state.candidate_since,
        ))
    return decisions


def fail_closed_cleanup_plan(
    records: list[dict[str, Any]],
    *,
    reason: str,
) -> list[CleanupDecision]:
    """处理失败清理计划相关后端逻辑。"""

    decisions: list[CleanupDecision] = []
    for record in records:
        memory_id = record.get("id")
        if not isinstance(memory_id, str):
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        retention_class = str(metadata.get("retention_class") or "core").lower()
        if retention_class not in {"core", "durable", "transient"}:
            retention_class = "core"
        decisions.append(CleanupDecision(
            memory_id=memory_id,
            action=CleanupAction.KEEP,
            retention_class=retention_class,
            reason=reason,
        ))
    return decisions


def public_cleanup_decision(decision: CleanupDecision) -> dict[str, Any]:
    """处理公开清理决策相关后端逻辑。"""

    return {
        "memory_id": decision.memory_id,
        "action": decision.action.value,
        "retention_class": decision.retention_class,
        "reason": decision.reason,
        "candidate_since": (
            decision.candidate_since.isoformat() if decision.candidate_since else None
        ),
    }


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _latest_datetime(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _safe_int(value: object) -> int:
    try:
        return max(0, int(str(value)))
    except (TypeError, ValueError):
        return 0


@lru_cache(maxsize=1)
def get_memory_retention_store() -> MemoryRetentionStore | None:
    """获取记忆保留存储相关后端逻辑。"""

    redis_url = get_settings().redis_url
    if not redis_url:
        return None
    return MemoryRetentionStore(Redis.from_url(redis_url, decode_responses=False))
