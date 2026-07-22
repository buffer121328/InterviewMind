"""通用 Agent 任务状态、恢复、取消、事件与列表服务。"""

import os
import uuid
from datetime import datetime, timedelta
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agent_definitions import get_agent_definition, get_agent_definitions
from app.domain.agent_runs import (
    ACTIVE_STATUSES,
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_INTERVIEW_TURN,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_RESUME_OPTIMIZE,
    TASK_TYPE_VOICE_INTERVIEW_TURN,
    TERMINAL_STATUSES,
    build_task_plan_from_steps,
    can_cancel_status,
)
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.db.models import AgentRunEventModel, AgentRunModel, async_session
from app.infrastructure.runtime.agent_runs.crypto import decrypt_payload, encrypt_payload
from app.infrastructure.runtime.agent_runs.outbox import enqueue_agent_run_outbox
from app.infrastructure.runtime.agent_runs.policies import allows_whole_run_retry

TASK_DEFINITIONS: dict[str, dict] = {
    definition.task_type: {"title": definition.title, "steps": definition.steps}
    for definition in get_agent_definitions()
}


def task_queue_enabled() -> bool:
    """判断是否启用异步任务队列。"""
    return os.getenv("TASK_QUEUE_ENABLED", "false").lower() == "true"


def _now() -> datetime:
    """当前时间快照（便于测试替换）。"""
    return datetime.now()


def max_attempts() -> int:
    """AgentRun 最大重试次数（环境变量配置）。"""
    return max(1, int(os.getenv("AGENT_RUN_MAX_ATTEMPTS", "3")))


def stale_after_seconds() -> int:
    """AgentRun 被视为"卡住"的超时秒数（环境变量配置）。"""
    return max(60, int(os.getenv("AGENT_RUN_STALE_SECONDS", "1800")))


def get_task_definition(task_type: str) -> dict:
    """获取任务类型的定义信息（标题 + 步骤列表），未知任务返回默认值。"""
    return TASK_DEFINITIONS.get(task_type, {"title": task_type, "steps": (("queued", "等待执行资源"),)})


def first_running_stage(task_type: str) -> str:
    """返回任务类型第一个"实际执行"阶段（跳过 queued）。"""
    steps = get_task_definition(task_type)["steps"]
    return steps[1][0] if len(steps) > 1 else steps[0][0]


def build_task_plan(task_type: str, stage: str, status: str) -> list[dict]:
    """构造前端可渲染的步骤计划列表，标记每个步骤的完成/运行/失败/等待状态。"""
    return build_task_plan_from_steps(
        get_task_definition(task_type)["steps"],
        stage=stage,
        status=status,
    )


def build_interview_start_plan(stage: str, status: str) -> list[dict]:
    """构建面试启动任务的步骤计划。"""
    return build_task_plan(TASK_TYPE_INTERVIEW_START, stage, status)


def serialize_run(run: AgentRunModel) -> dict:
    """将 AgentRun 模型序列化为 API 响应格式。"""
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
        "trace_id": getattr(run, "trace_id", None),
        "attempts": run.attempts,
        "max_attempts": max_attempts(),
        "can_retry": allows_whole_run_retry(run.task_type) and run.status in {"failed", "cancelled"} and run.attempts < max_attempts(),
        "can_cancel": can_cancel_status(run.status),
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def serialize_event(event: AgentRunEventModel) -> dict:
    """将 AgentRunEvent 模型序列化为 API 响应格式。"""
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
    """Agent 任务运行的生命周期管理服务。

    提供任务的创建、领取、执行阶段推进、取消、重试、恢复、完成/失败
    以及事件记录与查询等核心功能。
    """

    async def _append_event(
        self,
        session: AsyncSession,
        run: AgentRunModel,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentRunEventModel:
        """记录一条 AgentRun 事件到数据库。"""

        sequence = int(await session.scalar(
            select(func.coalesce(func.max(AgentRunEventModel.sequence), 0)).where(AgentRunEventModel.run_id == run.id)
        ) or 0) + 1     # 计算新事件的 sequence（序列号），即当前已有事件的序号最大值 + 1。
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

    async def record_observation(
        self,
        run_id: str,
        *,
        trace_id: str,
        model_events: list[dict[str, Any]] | None = None,
    ) -> None:
        """回填 AgentRun 与 Langfuse 的 trace 关联。

        `model_events` 由 Langfuse / LangChain 观测链路消费，业务数据库只保存
        trace_id，避免把模型、token、时延、成本、fallback 等遥测数据重复写入
        agent_runs 或 agent_run_events。保留参数是为了兼容 observability 适配层调用。
        """
        _ = model_events
        async with UnitOfWork(async_session) as uow:
            session = uow.db
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run:
                return

            run.trace_id = trace_id
            run.updated_at = _now()

    async def create_or_get(self, *, user_id: str, payload: dict, idempotency_key: str, task_type: str = TASK_TYPE_INTERVIEW_START) -> tuple[AgentRunModel, bool]:
        """幂等方式创建 AgentRun：同 user+type+idempotency_key 返回已有记录。"""
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

    async def get(self, run_id: str, user_id: str) -> AgentRunModel | None:
        """获取单个 AgentRun（带用户归属校验）。"""
        async with async_session() as session:
            return await session.scalar(select(AgentRunModel).where(AgentRunModel.id == run_id, AgentRunModel.user_id == user_id))

    async def list_runs(self, user_id: str, *, status: str | None = None, task_type: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[AgentRunModel], int]:
        """分页查询用户的 AgentRun 列表，支持按状态和类型过滤。"""
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
        """查询 AgentRun 的事件列表（支持增量游标）。"""
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
        """领取一个 queued/retrying 状态的 AgentRun 开始执行。"""
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
        """更新运行中 AgentRun 的阶段进度。"""
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
        """更新 AgentRun 的 updated_at 时间戳，防止被判定为"卡住"。"""
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status not in {"running", "cancel_requested"}:
                return
            run.updated_at = _now()
            await session.commit()

    async def is_cancel_requested(self, run_id: str) -> bool:
        """检查任务是否已被请求取消。"""
        async with async_session() as session:
            status = await session.scalar(select(AgentRunModel.status).where(AgentRunModel.id == run_id))
            return status == "cancel_requested"

    async def requeue(self, run_id: str) -> None:
        """将运行中的 AgentRun 重新放回队列（被取消请求时回退）。"""
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
        """重试一个失败或被取消的 AgentRun（检查重试策略和次数限制）。"""
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
        """恢复卡住的 AgentRun：处理取消请求、重新投递未领取或执行中断的任务。"""
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
        """恢复当前用户所有卡住的 AgentRun。"""
        return await self._recover(user_id=user_id, limit=200)

    async def recover_all_stale_runs(self, limit: int = 200) -> list[AgentRunModel]:
        """恢复系统中所有卡住的 AgentRun（管理员/Worker 使用）。"""
        return await self._recover(user_id=None, limit=limit)

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
        """标记 AgentRun 为成功状态，直接设置结果。"""
        async def result_writer(_session: AsyncSession) -> dict:
            """异步执行 `result_writer` 相关逻辑。

            Args:
                _session: 调用方传入的 `_session` 参数。
            """
            return result

        await self.succeed_with_result_writer(run_id, result_writer)

    async def succeed_with_result_writer(
        self,
        run_id: str,
        result_writer: Callable[[AsyncSession], Awaitable[dict]],
    ) -> None:
        """使用延迟持久化回调标记 AgentRun 成功（业务结果和 AgentRun 同一事务）。"""
        async with UnitOfWork(async_session) as uow:
            await self._succeed_in_session(uow.db, run_id, result_writer)

    async def fail(self, run_id: str, message: str) -> None:
        """标记 AgentRun 为失败状态（处理取消竞态）。"""
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
        """强制标记 AgentRun 为已取消（Worker 内部使用）。"""
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
        """取消 AgentRun：队列中直接取消，运行中发取消请求。"""
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
