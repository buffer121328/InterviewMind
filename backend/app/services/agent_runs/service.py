"""通用 Agent 任务状态、恢复、取消、事件与列表服务。"""

import os
import uuid
from datetime import datetime, timedelta
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.definitions import get_agent_definition, get_agent_definitions
from app.application.unit_of_work import UnitOfWork
from app.models import AgentRunEventModel, AgentRunModel, async_session
from app.services.agent_runs.crypto import decrypt_payload, encrypt_payload
from app.services.agent_runs.outbox import enqueue_agent_run_outbox
from app.services.agent_runs.policies import allows_whole_run_retry

TASK_TYPE_INTERVIEW_START = "interview_start"
TASK_TYPE_INTERVIEW_TURN = "interview_turn"
TASK_TYPE_VOICE_INTERVIEW_TURN = "voice_interview_turn"
TASK_TYPE_RESUME_OPTIMIZE = "resume_optimize"
TASK_TYPE_INTERVIEW_REPORT = "interview_report"
TASK_TYPE_JOB_ASSETS = "job_assets"
ACTIVE_STATUSES = {"queued", "retrying", "running", "cancel_requested"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

TASK_DEFINITIONS: dict[str, dict] = {
    definition.task_type: {"title": definition.title, "steps": definition.steps}
    for definition in get_agent_definitions()
}


def task_queue_enabled() -> bool:
    return os.getenv("TASK_QUEUE_ENABLED", "false").lower() == "true"


def _now() -> datetime:
    return datetime.now()


def max_attempts() -> int:
    return max(1, int(os.getenv("AGENT_RUN_MAX_ATTEMPTS", "3")))


def stale_after_seconds() -> int:
    return max(60, int(os.getenv("AGENT_RUN_STALE_SECONDS", "1800")))


def get_task_definition(task_type: str) -> dict:
    return TASK_DEFINITIONS.get(task_type, {"title": task_type, "steps": (("queued", "等待执行资源"),)})


def first_running_stage(task_type: str) -> str:
    steps = get_task_definition(task_type)["steps"]
    return steps[1][0] if len(steps) > 1 else steps[0][0]


def build_task_plan(task_type: str, stage: str, status: str) -> list[dict]:
    steps = get_task_definition(task_type)["steps"]
    stage_index = next((index for index, item in enumerate(steps) if item[0] == stage), -1)
    terminal_success = status == "succeeded"
    terminal_failure = status in {"failed", "cancelled"}
    if terminal_failure and stage_index < 0:
        stage_index = 0
    plan: list[dict] = []
    for index, (step_id, title) in enumerate(steps):
        if terminal_success or index < stage_index:
            step_status = "completed"
        elif index == stage_index:
            step_status = "failed" if terminal_failure else "running"
        else:
            step_status = "pending"
        plan.append({"id": step_id, "title": title, "status": step_status})
    return plan


def build_interview_start_plan(stage: str, status: str) -> list[dict]:
    return build_task_plan(TASK_TYPE_INTERVIEW_START, stage, status)


def serialize_run(run: AgentRunModel) -> dict:
    definition = get_task_definition(run.task_type)
    agent_definition = get_agent_definition(run.task_type)
    return {
        "run_id": run.id,
        "agent_name": getattr(run, "agent_name", None) or agent_definition.name,
        "agent_version": getattr(run, "agent_version", None) or agent_definition.version,
        "task_type": run.task_type,
        "title": definition["title"],
        "status": run.status,
        "stage": run.stage,
        "plan": build_task_plan(run.task_type, run.stage, run.status),
        "result": run.result,
        "error_message": run.error_message,
        "attempts": run.attempts,
        "max_attempts": max_attempts(),
        "can_retry": allows_whole_run_retry(run.task_type) and run.status in {"failed", "cancelled"} and run.attempts < max_attempts(),
        "can_cancel": run.status in {"queued", "retrying", "running", "cancel_requested"},
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def serialize_event(event: AgentRunEventModel) -> dict:
    return {
        "event_id": str(event.id),
        "run_id": event.run_id,
        "sequence": event.sequence,
        "type": event.event_type,
        "stage": event.stage,
        "payload": event.payload or {},
        "schema_version": event.schema_version,
        "timestamp": event.created_at.isoformat(),
    }


class AgentRunService:
    async def _append_event(
        self,
        session: AsyncSession,
        run: AgentRunModel,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentRunEventModel:
        sequence = int(await session.scalar(
            select(func.coalesce(func.max(AgentRunEventModel.sequence), 0)).where(AgentRunEventModel.run_id == run.id)
        ) or 0) + 1
        event = AgentRunEventModel(
            run_id=run.id,
            sequence=sequence,
            event_type=event_type,
            stage=run.stage,
            payload=payload or {},
            schema_version=1,
            created_at=_now(),
        )
        session.add(event)
        return event

    async def create_or_get(self, *, user_id: str, payload: dict, idempotency_key: str, task_type: str = TASK_TYPE_INTERVIEW_START) -> tuple[AgentRunModel, bool]:
        if task_type not in TASK_DEFINITIONS:
            raise ValueError(f"unknown task type: {task_type}")
        async with async_session() as session:
            existing = await session.scalar(select(AgentRunModel).where(
                AgentRunModel.user_id == user_id,
                AgentRunModel.task_type == task_type,
                AgentRunModel.idempotency_key == idempotency_key,
            ))
            if existing:
                return existing, False
            now = _now()
            definition = get_agent_definition(task_type)
            run = AgentRunModel(
                id=str(uuid.uuid4()), user_id=user_id, task_type=task_type,
                agent_name=definition.name, agent_version=definition.version, status="queued", stage="queued",
                idempotency_key=idempotency_key, payload_encrypted=encrypt_payload(payload), result=None,
                error_message=None, attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
            )
            session.add(run)
            await session.flush()
            await self._append_event(session, run, "run.created", {
                "task_type": task_type,
                "agent_name": definition.name,
                "agent_version": definition.version,
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

    async def get(self, run_id: str, user_id: str) -> AgentRunModel | None:
        async with async_session() as session:
            return await session.scalar(select(AgentRunModel).where(AgentRunModel.id == run_id, AgentRunModel.user_id == user_id))

    async def list_runs(self, user_id: str, *, status: str | None = None, task_type: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[AgentRunModel], int]:
        async with async_session() as session:
            filters = [AgentRunModel.user_id == user_id]
            if status:
                filters.append(AgentRunModel.status == status)
            if task_type:
                filters.append(AgentRunModel.task_type == task_type)
            rows = await session.scalars(select(AgentRunModel).where(*filters).order_by(AgentRunModel.created_at.desc()).limit(limit).offset(offset))
            total = await session.scalar(select(func.count(AgentRunModel.id)).where(*filters))
            return list(rows), int(total or 0)

    async def list_events(self, run_id: str, user_id: str, *, after_sequence: int = 0, limit: int = 200) -> list[AgentRunEventModel] | None:
        async with async_session() as session:
            owned = await session.scalar(select(AgentRunModel.id).where(AgentRunModel.id == run_id, AgentRunModel.user_id == user_id))
            if not owned:
                return None
            rows = await session.scalars(select(AgentRunEventModel).where(
                AgentRunEventModel.run_id == run_id,
                AgentRunEventModel.sequence > after_sequence,
            ).order_by(AgentRunEventModel.sequence).limit(limit))
            return list(rows)

    async def claim(self, run_id: str) -> tuple[AgentRunModel, dict] | None:
        async with async_session() as session:
            run = await session.scalar(select(AgentRunModel).where(AgentRunModel.id == run_id).with_for_update())
            if not run or run.status not in {"queued", "retrying"}:
                return None
            now = _now()
            run.status = "running"
            run.stage = first_running_stage(run.task_type)
            run.attempts += 1
            run.started_at = now
            run.finished_at = None
            run.updated_at = now
            await self._append_event(session, run, "run.started", {"attempt": run.attempts})
            await session.commit()
            await session.refresh(run)
            return run, decrypt_payload(run.payload_encrypted)

    async def mark_stage(self, run_id: str, stage: str) -> None:
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status != "running":
                return
            valid_stages = {item[0] for item in get_task_definition(run.task_type)["steps"]}
            if stage not in valid_stages:
                raise ValueError(f"invalid stage for {run.task_type}: {stage}")
            if run.stage == stage:
                return
            run.stage = stage
            run.updated_at = _now()
            await self._append_event(session, run, "run.stage.changed")
            await session.commit()

    async def touch(self, run_id: str) -> None:
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status not in {"running", "cancel_requested"}:
                return
            run.updated_at = _now()
            await session.commit()

    async def is_cancel_requested(self, run_id: str) -> bool:
        async with async_session() as session:
            status = await session.scalar(select(AgentRunModel.status).where(AgentRunModel.id == run_id))
            return status == "cancel_requested"

    async def requeue(self, run_id: str) -> None:
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status not in {"running", "cancel_requested"}:
                return
            run.status = "queued"
            run.stage = "queued"
            now = _now()
            run.updated_at = now
            await self._append_event(session, run, "run.requeued")
            await enqueue_agent_run_outbox(session, run.id, now=now)
            await session.commit()

    async def retry(self, run_id: str, user_id: str) -> AgentRunModel | None:
        async with async_session() as session:
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
            now = _now()
            run.updated_at = now
            await self._append_event(session, run, "run.retry.requested", {"next_attempt": run.attempts + 1})
            await enqueue_agent_run_outbox(session, run.id, now=now)
            await session.commit()
            await session.refresh(run)
            return run

    async def _recover(self, *, user_id: str | None, limit: int) -> list[AgentRunModel]:
        cutoff = _now() - timedelta(seconds=stale_after_seconds())
        recovered: list[AgentRunModel] = []
        async with async_session() as session:
            filters = [AgentRunModel.status.in_(ACTIVE_STATUSES), AgentRunModel.updated_at < cutoff]
            if user_id is not None:
                filters.append(AgentRunModel.user_id == user_id)
            rows = await session.scalars(select(AgentRunModel).where(*filters).order_by(AgentRunModel.updated_at).limit(limit).with_for_update(skip_locked=True))
            now = _now()
            for run in rows:
                run.result = None
                run.updated_at = now
                if run.status == "cancel_requested":
                    run.status = "cancelled"
                    run.stage = "cancelled"
                    run.error_message = "取消请求已完成"
                    run.finished_at = now
                    await self._append_event(session, run, "run.cancelled", {"reason": "stale_cancel_request"})
                elif run.status in {"queued", "retrying"}:
                    run.status = "retrying"
                    run.stage = "queued"
                    run.error_message = "检测到任务长时间未被领取，已自动重新投递"
                    run.finished_at = None
                    recovered.append(run)
                    await self._append_event(session, run, "run.recovered", {"reason": "not_claimed"})
                    await enqueue_agent_run_outbox(session, run.id, now=now)
                elif run.attempts < max_attempts():
                    run.status = "retrying"
                    run.stage = "queued"
                    run.error_message = "检测到任务执行中断，已自动恢复等待重试"
                    run.finished_at = None
                    recovered.append(run)
                    await self._append_event(session, run, "run.recovered", {"reason": "worker_interrupted"})
                    await enqueue_agent_run_outbox(session, run.id, now=now)
                else:
                    run.status = "failed"
                    run.error_message = "任务执行中断且已达到最大尝试次数"
                    run.finished_at = now
                    await self._append_event(session, run, "run.failed", {"reason": "max_attempts"})
            await session.commit()
            for run in recovered:
                await session.refresh(run)
        return recovered

    async def recover_stale_runs(self, user_id: str) -> list[AgentRunModel]:
        return await self._recover(user_id=user_id, limit=200)

    async def recover_all_stale_runs(self, limit: int = 200) -> list[AgentRunModel]:
        return await self._recover(user_id=None, limit=limit)

    async def _succeed_in_session(
        self,
        session: AsyncSession,
        run_id: str,
        result_writer: Callable[[AsyncSession], Awaitable[dict]],
    ) -> None:
        run = await session.get(AgentRunModel, run_id, with_for_update=True)
        if not run or run.status == "cancelled":
            return
        now = _now()
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
            run.error_message = None
            run.updated_at = now
            run.finished_at = now
            await self._append_event(session, run, "run.completed")

    async def succeed(self, run_id: str, result: dict) -> None:
        async def result_writer(_session: AsyncSession) -> dict:
            return result

        await self.succeed_with_result_writer(run_id, result_writer)

    async def succeed_with_result_writer(
        self,
        run_id: str,
        result_writer: Callable[[AsyncSession], Awaitable[dict]],
    ) -> None:
        async with UnitOfWork(async_session) as uow:
            await self._succeed_in_session(uow.db, run_id, result_writer)

    async def fail(self, run_id: str, message: str) -> None:
        async with UnitOfWork(async_session) as uow:
            session = uow.db
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status == "cancelled":
                return
            now = _now()
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
        async with UnitOfWork(async_session) as uow:
            session = uow.db
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status == "cancelled":
                return
            now = _now()
            run.status = "cancelled"
            run.stage = "cancelled"
            run.error_message = message
            run.updated_at = now
            run.finished_at = now
            await self._append_event(session, run, "run.cancelled", {"message": message})

    async def cancel(self, run_id: str, user_id: str) -> AgentRunModel | None:
        async with async_session() as session:
            run = await session.scalar(select(AgentRunModel).where(AgentRunModel.id == run_id, AgentRunModel.user_id == user_id).with_for_update())
            if not run or run.status not in {"queued", "retrying", "running", "cancel_requested"}:
                return None
            now = _now()
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
