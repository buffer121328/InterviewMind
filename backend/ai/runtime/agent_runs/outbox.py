"""任务投递 Outbox：保证任务创建后 Broker 投递可补偿重试。"""

from __future__ import annotations

from datetime import datetime, timedelta
import time
from typing import Callable, Iterable

from sqlalchemy import select

from app.db.models import TaskOutboxModel, async_session

AGENT_RUN_EXECUTE_TOPIC = "agent_run.execute"
PENDING_STATUSES = {"pending", "failed"}


def _now() -> datetime:
    """当前时间快照（便于测试替换）。"""
    return datetime.now()


def next_retry_at(now: datetime, attempts: int) -> datetime:
    """指数退避，最长 5 分钟；attempts 为失败后的累计次数。"""
    delay_seconds = min(300, 2 ** max(0, attempts - 1))
    return now + timedelta(seconds=delay_seconds)


async def enqueue_agent_run_outbox(session, run_id: str, *, now: datetime | None = None) -> TaskOutboxModel:
    """在当前数据库事务中登记 AgentRun 投递消息。

    同一个 run 可能经历创建、用户重试、陈旧恢复等多轮投递；这里按
    `(topic, message_key)` 幂等复用旧记录，并重新置为 pending。
    """
    current = now or _now()
    item = await session.scalar(
        select(TaskOutboxModel)
        .where(
            TaskOutboxModel.topic == AGENT_RUN_EXECUTE_TOPIC,
            TaskOutboxModel.message_key == run_id,
        )
        .with_for_update()
    )
    if item is None:
        item = TaskOutboxModel(
            topic=AGENT_RUN_EXECUTE_TOPIC,
            message_key=run_id,
            payload={"run_id": run_id},
            status="pending",
            attempts=0,
            next_attempt_at=current,
            created_at=current,
            updated_at=current,
            dispatched_at=None,
            last_attempt_at=None,
            last_attempt_duration_ms=None,
            last_error=None,
            last_error_type=None,
            last_failure_reason=None,
        )
        session.add(item)
        return item

    item.payload = {"run_id": run_id}
    item.status = "pending"
    item.attempts = 0
    item.next_attempt_at = current
    item.updated_at = current
    item.dispatched_at = None
    item.last_attempt_at = None
    item.last_attempt_duration_ms = None
    item.last_error = None
    item.last_error_type = None
    item.last_failure_reason = None
    return item


def classify_dispatch_error(error: Exception) -> tuple[str, str]:
    """将投递异常分类为 (error_type, failure_reason) 便于后续排查。"""
    if isinstance(error, KeyError):
        return type(error).__name__, "invalid_payload"
    if isinstance(error, (ConnectionError, TimeoutError)):
        return type(error).__name__, "broker_unavailable"
    return type(error).__name__, "dispatch_error"


def mark_dispatched(
    item: TaskOutboxModel,
    *,
    now: datetime | None = None,
    duration_ms: int | None = None,
) -> None:
    """将 outbox item 标记为已投递，清除上次失败信息。"""
    current = now or _now()
    item.status = "dispatched"
    item.dispatched_at = current
    item.last_attempt_at = current
    item.last_attempt_duration_ms = duration_ms
    item.updated_at = current
    item.last_error = None
    item.last_error_type = None
    item.last_failure_reason = None


def mark_dispatch_failed(
    item: TaskOutboxModel,
    error: Exception,
    *,
    now: datetime | None = None,
    duration_ms: int | None = None,
) -> None:
    """将 outbox item 标记为投递失败，记录错误信息并计算下次重试时间。"""
    current = now or _now()
    error_type, reason = classify_dispatch_error(error)
    item.status = "failed"
    item.attempts += 1
    item.last_attempt_at = current
    item.last_attempt_duration_ms = duration_ms
    item.last_error = str(error)[:500]
    item.last_error_type = error_type[:100]
    item.last_failure_reason = reason
    item.next_attempt_at = next_retry_at(current, item.attempts)
    item.updated_at = current


def dispatch_outbox_items(
    items: Iterable[TaskOutboxModel],
    *,
    enqueue_fn: Callable[[str], None],
    now: datetime | None = None,
) -> tuple[int, int]:
    """投递已领取的 outbox items，返回 (成功数, 失败数)。"""
    success = 0
    failed = 0
    current = now or _now()
    for item in items:
        started = time.perf_counter()
        try:
            run_id = item.payload["run_id"]
            enqueue_fn(run_id)
        except Exception as exc:  # noqa: BLE001 - 需要记录任意 Broker 投递失败
            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            mark_dispatch_failed(item, exc, now=current, duration_ms=duration_ms)
            failed += 1
        else:
            duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            mark_dispatched(item, now=current, duration_ms=duration_ms)
            success += 1
    return success, failed


async def dispatch_pending_outbox(
    *,
    limit: int = 100,
    enqueue_fn: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    """扫描 pending/failed outbox 并投递 Broker。

    当前实现使用 `FOR UPDATE SKIP LOCKED` 支持多实例并发扫描；投递成功后标记
    dispatched，失败时保留 failed 并设置 next_attempt_at 供后续重试。
    """
    if enqueue_fn is None:
        from ai.runtime.agent_runs.dispatcher import enqueue_agent_run

        enqueue_fn = enqueue_agent_run

    current = _now()
    async with async_session() as session:
        rows = await session.scalars(
            select(TaskOutboxModel)
            .where(
                TaskOutboxModel.topic == AGENT_RUN_EXECUTE_TOPIC,
                TaskOutboxModel.status.in_(PENDING_STATUSES),
                TaskOutboxModel.next_attempt_at <= current,
            )
            .order_by(TaskOutboxModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        success, failed = dispatch_outbox_items(list(rows), enqueue_fn=enqueue_fn, now=current)
        await session.commit()
        return success, failed
