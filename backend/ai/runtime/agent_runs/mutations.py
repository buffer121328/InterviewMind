from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai.runtime.agent_runs.definitions import (
    TASK_DEFINITIONS,
    first_running_stage,
    get_task_definition,
)
from ai.runtime.agent_runs.outbox import enqueue_agent_run_outbox
from ai.runtime.agent_runs.policies import allows_whole_run_retry
from ai.runtime.agent_runs.settings import max_attempts
from app.db.models import (
    AgentRunModel,
)
from app.domain.agent_definitions import get_agent_definition
from app.domain.agent_runs import (
    TASK_TYPE_INTERVIEW_START,
)


def _queue_wait_ms(run: AgentRunModel, now) -> int:
    """按首次排队或最近一次重试入队时间计算非负队列等待毫秒数。"""

    queued_since = run.updated_at if run.status == "retrying" else run.created_at
    return max(0, int((now - queued_since).total_seconds() * 1000))


class AgentRunMutationsMixin:
    async def create_or_get(
            self,
            *,
            user_id: str,
            payload: dict,
            idempotency_key: str,
            task_type: str = TASK_TYPE_INTERVIEW_START,
            session_id: str | None = None,
        ) -> tuple[AgentRunModel, bool]:
            """幂等方式创建 AgentRun：同 user+type+idempotency_key 返回已有记录。"""
            if task_type not in TASK_DEFINITIONS:
                raise ValueError(f"unknown task type: {task_type}")
            definition = get_agent_definition(task_type)
            async with self._runtime_async_session() as session:
                existing = await session.scalar(select(AgentRunModel).where(
                    AgentRunModel.user_id == user_id,
                    AgentRunModel.task_type == task_type,
                    AgentRunModel.idempotency_key == idempotency_key,
                ))
                if existing:
                    return existing, False
                now = self._runtime_now()
                run = AgentRunModel(
                    id=str(uuid.uuid4()), user_id=user_id, session_id=session_id, task_type=task_type,
                    agent_name=definition.name, agent_version=definition.version, status="queued", stage="queued",
                    idempotency_key=idempotency_key, payload_encrypted=self._runtime_encrypt_payload(payload), result=None,
                    step_results={},
                    error_message=None, attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
                )
                session.add(run)
                await session.flush()
                await self._append_event(session, run, "run.created", {
                    "task_type": task_type,
                    "agent_name": definition.name,
                    "agent_version": definition.version,
                    "prompt_name": definition.prompt_name,
                    "prompt_version": definition.prompt_version,
                    "checkpoint_policy": definition.checkpoint_policy,
                    "cancellation_policy": definition.cancellation_policy,
                })
                await enqueue_agent_run_outbox(session, run.id, now=now)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    existing = await session.scalar(select(AgentRunModel).where(
                        AgentRunModel.user_id == user_id,
                        AgentRunModel.task_type == task_type,
                        AgentRunModel.idempotency_key == idempotency_key,
                    ))
                    if existing:
                        return existing, False
                    raise
                await session.refresh(run)
                return run, True

    async def create_inline_or_get(
            self,
            *,
            user_id: str,
            payload: dict,
            idempotency_key: str,
            task_type: str,
            initial_stage: str,
            session_id: str | None = None,
        ) -> tuple[AgentRunModel, bool]:
            """创建行内相关后端逻辑。"""
            if task_type not in TASK_DEFINITIONS:
                raise ValueError(f"unknown task type: {task_type}")
            definition = get_agent_definition(task_type)
            valid_stages = [step_id for step_id, _title in definition.steps]
            if initial_stage not in valid_stages or initial_stage == "queued":
                raise ValueError(f"invalid initial stage for {task_type}: {initial_stage}")

            async with self._runtime_async_session() as session:
                existing = await session.scalar(select(AgentRunModel).where(
                    AgentRunModel.user_id == user_id,
                    AgentRunModel.task_type == task_type,
                    AgentRunModel.idempotency_key == idempotency_key,
                ))
                if existing:
                    return existing, False

                now = self._runtime_now()
                stage_index = valid_stages.index(initial_stage)
                step_results = {
                    step_id: {"status": "completed", "finished_at": now.isoformat()}
                    for step_id in valid_stages[1:stage_index]
                }
                step_results[initial_stage] = {
                    "status": "running",
                    "started_at": now.isoformat(),
                }
                run = AgentRunModel(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    session_id=session_id,
                    task_type=task_type,
                    agent_name=definition.name,
                    agent_version=definition.version,
                    status="running",
                    stage=initial_stage,
                    idempotency_key=idempotency_key,
                    payload_encrypted=self._runtime_encrypt_payload(payload),
                    result=None,
                    step_results=step_results,
                    error_message=None,
                    attempts=1,
                    created_at=now,
                    updated_at=now,
                    started_at=now,
                    finished_at=None,
                )
                session.add(run)
                await session.flush()
                await self._append_event(session, run, "run.created", {
                    "task_type": task_type,
                    "agent_name": definition.name,
                    "agent_version": definition.version,
                    "prompt_name": definition.prompt_name,
                    "prompt_version": definition.prompt_version,
                    "checkpoint_policy": definition.checkpoint_policy,
                    "cancellation_policy": definition.cancellation_policy,
                    "execution_mode": "interactive_inline",
                })
                await self._append_event(
                    session,
                    run,
                    "run.started",
                    {"attempt": 1, "queue_wait_ms": 0},
                )
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    existing = await session.scalar(select(AgentRunModel).where(
                        AgentRunModel.user_id == user_id,
                        AgentRunModel.task_type == task_type,
                        AgentRunModel.idempotency_key == idempotency_key,
                    ))
                    if existing:
                        return existing, False
                    raise
                await session.refresh(run)
                return run, True

    async def claim(self, run_id: str) -> tuple[AgentRunModel, dict] | None:
            """领取一个 queued/retrying 状态的 AgentRun 开始执行。"""
            async with self._runtime_async_session() as session:
                run = await session.scalar(select(AgentRunModel).where(AgentRunModel.id == run_id).with_for_update())
                if not run or run.status not in {"queued", "retrying"}:
                    return None
                now = self._runtime_now()
                queue_wait_ms = _queue_wait_ms(run, now)
                run.status = "running"
                run.stage = first_running_stage(run.task_type)
                run.attempts += 1
                run.started_at = now
                run.finished_at = None
                run.updated_at = now
                await self._append_event(
                    session,
                    run,
                    "run.started",
                    {"attempt": run.attempts, "queue_wait_ms": queue_wait_ms},
                )
                await session.commit()
                await session.refresh(run)
                return run, self._runtime_decrypt_payload(run.payload_encrypted)

    async def mark_stage(self, run_id: str, stage: str) -> None:
            """推进运行阶段并持久化步骤完成记录，不写入敏感任务载荷或模型原文。"""
            async with self._runtime_async_session() as session:
                run = await session.get(AgentRunModel, run_id, with_for_update=True)
                if not run or run.status != "running":
                    return
                valid_stages = {item[0] for item in get_task_definition(run.task_type)["steps"]}
                if stage not in valid_stages:
                    raise ValueError(f"invalid stage for {run.task_type}: {stage}")
                if run.stage == stage:
                    return
                now = self._runtime_now()
                step_results = dict(run.step_results or {})
                if run.stage in valid_stages and run.stage != "queued":
                    prior = dict(step_results.get(run.stage) or {})
                    prior.update({"status": "completed", "finished_at": now.isoformat()})
                    step_results[run.stage] = prior
                current = dict(step_results.get(stage) or {})
                current.update({"status": "running", "started_at": current.get("started_at") or now.isoformat()})
                step_results[stage] = current
                run.stage = stage
                run.step_results = step_results
                run.updated_at = now
                await self._append_event(session, run, "run.stage.changed")
                await session.commit()

    async def save_checkpoint(
            self,
            run_id: str,
            stage: str,
            checkpoint: dict[str, Any],
            *,
            user_id: str,
        ) -> None:
            """按 owner 加密保存恢复 checkpoint，事件仅记录不含正文的阶段摘要。"""
            async with self._runtime_async_session() as session:
                run = await session.scalar(
                    select(AgentRunModel)
                    .where(
                        AgentRunModel.id == run_id,
                        AgentRunModel.user_id == user_id,
                    )
                    .with_for_update()
                )
                if not run or run.status not in {"running", "cancel_requested"}:
                    return
                valid_stages = {item[0] for item in get_task_definition(run.task_type)["steps"]}
                if stage not in valid_stages:
                    raise ValueError(f"invalid checkpoint stage for {run.task_type}: {stage}")
                now = self._runtime_now()
                step_results = dict(run.step_results or {})
                step = dict(step_results.get(stage) or {})
                step["checkpoint_encrypted"] = self._runtime_encrypt_payload(checkpoint)
                step["checkpoint_updated_at"] = now.isoformat()
                step_results[stage] = step
                run.step_results = step_results
                run.updated_at = now
                item_count = len(checkpoint.get("items") or []) if isinstance(checkpoint, dict) else 0
                await self._append_event(session, run, "run.checkpoint.saved", {"item_count": item_count})
                await session.commit()

    async def load_checkpoint(self, run_id: str, user_id: str, stage: str) -> dict[str, Any] | None:
            """按 owner 读取并解密恢复 checkpoint；密文不存在时返回 None。"""
            async with self._runtime_async_session() as session:
                run = await session.scalar(
                    select(AgentRunModel).where(
                        AgentRunModel.id == run_id,
                        AgentRunModel.user_id == user_id,
                    )
                )
                if not run:
                    return None
                step = dict((run.step_results or {}).get(stage) or {})
                encrypted = step.get("checkpoint_encrypted")
                if not isinstance(encrypted, str) or not encrypted:
                    return None
                value = self._runtime_decrypt_payload(encrypted)
                return value if isinstance(value, dict) else None

    async def touch(self, run_id: str) -> None:
            """更新 AgentRun 的 updated_at 时间戳，防止被判定为"卡住"。"""
            async with self._runtime_async_session() as session:
                run = await session.get(AgentRunModel, run_id, with_for_update=True)
                if not run or run.status not in {"running", "cancel_requested"}:
                    return
                run.updated_at = self._runtime_now()
                await session.commit()

    async def is_cancel_requested(self, run_id: str) -> bool:
            """检查任务是否已被请求取消。"""
            async with self._runtime_async_session() as session:
                status = await session.scalar(select(AgentRunModel.status).where(AgentRunModel.id == run_id))
                return status == "cancel_requested"

    async def requeue(self, run_id: str) -> None:
            """将运行中的 AgentRun 重新放回队列（被取消请求时回退）。"""
            async with self._runtime_async_session() as session:
                run = await session.get(AgentRunModel, run_id, with_for_update=True)
                if not run or run.status not in {"running", "cancel_requested"}:
                    return
                run.status = "queued"
                run.stage = "queued"
                now = self._runtime_now()
                run.updated_at = now
                await self._append_event(session, run, "run.requeued")
                await enqueue_agent_run_outbox(session, run.id, now=now)
                await session.commit()

    async def retry(self, run_id: str, user_id: str) -> AgentRunModel | None:
            """重试一个失败或被取消的 AgentRun（检查重试策略和次数限制）。"""
            async with self._runtime_async_session() as session:
                run = await session.scalar(select(AgentRunModel).where(AgentRunModel.id == run_id, AgentRunModel.user_id == user_id).with_for_update())
                if (
                    not run
                    or not allows_whole_run_retry(run.task_type)
                    or run.status not in {"failed", "cancelled"}
                    or run.attempts >= max_attempts()
                ):
                    return None
                run.status = "retrying"
                run.stage = "queued"
                run.result = None
                run.error_message = None
                run.finished_at = None
                now = self._runtime_now()
                run.updated_at = now
                await self._append_event(session, run, "run.retry.requested", {"next_attempt": run.attempts + 1})
                await enqueue_agent_run_outbox(session, run.id, now=now)
                await session.commit()
                await session.refresh(run)
                return run

    async def _succeed_in_session(
            self,
            session: AsyncSession,
            run_id: str,
            result_writer: Callable[[AsyncSession], Awaitable[dict]],
        ) -> None:
            """在事务内标记 AgentRun 成功：处理取消竞态，写入业务结果。"""
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status == "cancelled":
                return
            now = self._runtime_now()
            if run.status == "cancel_requested":
                run.status = "cancelled"
                run.stage = "cancelled"
                run.error_message = "任务已取消"
                run.finished_at = now
                run.updated_at = now
                await self._append_event(session, run, "run.cancelled", {"reason": "cancel_won_race"})
            else:
                result = await result_writer(session)
                run.status = "succeeded"
                run.stage = "succeeded"
                run.result = result
                step_results = dict(run.step_results or {})
                for step_id, _title in get_task_definition(run.task_type)["steps"]:
                    if step_id == "queued":
                        continue
                    step = dict(step_results.get(step_id) or {})
                    step.update({"status": "completed", "finished_at": now.isoformat()})
                    step.pop("checkpoint_encrypted", None)
                    step_results[step_id] = step
                run.step_results = step_results
                run.error_message = None
                run.updated_at = now
                run.finished_at = now
                await self._append_event(session, run, "run.completed")

    async def succeed(self, run_id: str, result: dict) -> None:
            """标记 AgentRun 为成功状态，直接设置结果。"""
            async def result_writer(_session: AsyncSession) -> dict:
                """将后台任务结果写入 AgentRun 和关联业务表，遵守 owner、事务和脱敏边界。

                Args:
                    _session: 经过类型边界校验的 `_session`；其格式和可选值由参数类型及调用流程约束。
                """
                return result

            await self.succeed_with_result_writer(run_id, result_writer)

    async def succeed_with_result_writer(
            self,
            run_id: str,
            result_writer: Callable[[AsyncSession], Awaitable[dict]],
        ) -> None:
            """使用延迟持久化回调标记 AgentRun 成功（业务结果和 AgentRun 同一事务）。"""
            async with self._runtime_unit_of_work() as uow:
                await self._succeed_in_session(uow.db, run_id, result_writer)

    async def fail(self, run_id: str, message: str) -> None:
            """标记 AgentRun 为失败状态（处理取消竞态）。"""
            async with self._runtime_unit_of_work() as uow:
                session = uow.db
                run = await session.get(AgentRunModel, run_id, with_for_update=True)
                if not run or run.status == "cancelled":
                    return
                now = self._runtime_now()
                if run.status == "cancel_requested":
                    run.status = "cancelled"
                    run.stage = "cancelled"
                    run.error_message = "任务已取消"
                    event_type = "run.cancelled"
                else:
                    run.status = "failed"
                    run.error_message = message[:300]
                    event_type = "run.failed"
                run.updated_at = now
                run.finished_at = now
                await self._append_event(session, run, event_type, {"message": run.error_message})

    async def mark_cancelled(self, run_id: str, message: str = "任务已取消") -> None:
            """强制标记 AgentRun 为已取消（Worker 内部使用）。"""
            async with self._runtime_unit_of_work() as uow:
                session = uow.db
                run = await session.get(AgentRunModel, run_id, with_for_update=True)
                if not run or run.status == "cancelled":
                    return
                now = self._runtime_now()
                run.status = "cancelled"
                run.stage = "cancelled"
                run.error_message = message
                run.updated_at = now
                run.finished_at = now
                await self._append_event(session, run, "run.cancelled", {"message": message})

    async def cancel(self, run_id: str, user_id: str) -> AgentRunModel | None:
            """取消 AgentRun：队列中直接取消，运行中发取消请求。"""
            async with self._runtime_async_session() as session:
                run = await session.scalar(select(AgentRunModel).where(AgentRunModel.id == run_id, AgentRunModel.user_id == user_id).with_for_update())
                if not run or run.status not in {"queued", "retrying", "running", "cancel_requested"}:
                    return None
                now = self._runtime_now()
                if run.status in {"queued", "retrying"}:
                    run.status = "cancelled"
                    run.stage = "cancelled"
                    run.finished_at = now
                    run.error_message = "任务已取消"
                    await self._append_event(session, run, "run.cancelled", {"immediate": True})
                elif run.status == "running":
                    run.status = "cancel_requested"
                    run.error_message = "正在请求取消当前任务"
                    await self._append_event(session, run, "run.cancel.requested")
                run.updated_at = now
                await session.commit()
                await session.refresh(run)
                return run
