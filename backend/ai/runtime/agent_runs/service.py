"""通用 Agent 任务状态、恢复、取消、事件与列表服务。

已知超限：职责单一（AgentRun 生命周期聚合），暂不拆分。
"""

import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai.runtime.agent_runs.outbox import enqueue_agent_run_outbox
from ai.runtime.agent_runs.policies import allows_whole_run_retry
from app.db.models import AgentRunEventModel, AgentRunModel, ModelMetricEventModel, SessionModel, async_session
from app.db.unit_of_work import UnitOfWork
from app.domain.agent_definitions import get_agent_definition, get_agent_definitions
from app.domain.agent_runs import (
    ACTIVE_STATUSES,
    TASK_TYPE_INTERVIEW_START,
    TERMINAL_STATUSES,
    build_task_plan_from_steps,
    can_cancel_status,
)
from app.security.security import redact_secrets
from app.security.payload_crypto import decrypt_payload, encrypt_payload
from app.clock import utc_now

TASK_DEFINITIONS: dict[str, dict] = {
    definition.task_type: {"title": definition.title, "steps": definition.steps}
    for definition in get_agent_definitions()
}

def task_queue_enabled() -> bool:
    """判断是否启用异步任务队列。"""
    return os.getenv("TASK_QUEUE_ENABLED", "true").lower() == "true"


def _now() -> datetime:
    """当前时间快照（便于测试替换）。"""
    return utc_now()


def _queue_wait_ms(run: AgentRunModel, now: datetime) -> int:
    """按首次排队或最近一次重试入队时间计算非负队列等待毫秒数。"""
    queued_since = run.updated_at if run.status == "retrying" else run.created_at
    return max(0, int((now - queued_since).total_seconds() * 1000))


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


def _public_step_results(value: dict | None) -> dict:
    """移除步骤状态中的加密恢复载荷，只向客户端暴露时间和状态摘要。"""
    public: dict[str, dict] = {}
    for step_id, raw in (value or {}).items():
        step = dict(raw or {})
        step.pop("checkpoint_encrypted", None)
        public[str(step_id)] = step
    return public


def serialize_run(run: AgentRunModel) -> dict:
    """将 AgentRun 模型序列化为 API 响应格式，不公开加密任务输入。"""
    definition = get_task_definition(run.task_type)
    agent_definition = get_agent_definition(run.task_type)
    return {
        "run_id": run.id,
        "session_id": getattr(run, "session_id", None),
        # Only set by an ownership-scoped lookup; never derive session display data
        # from the encrypted task payload.
        "session_title": getattr(run, "session_title", None),
        "session_status": getattr(run, "session_status", None),
        "session_question_count": getattr(run, "session_question_count", None),
        "session_max_questions": getattr(run, "session_max_questions", None),
        "agent_name": getattr(run, "agent_name", None) or agent_definition.name,
        "agent_version": getattr(run, "agent_version", None) or agent_definition.version,
        "task_type": run.task_type,
        "title": definition["title"],
        "status": run.status,
        "stage": run.stage,
        "plan": build_task_plan(run.task_type, run.stage, run.status),
        "result": run.result,
        "step_results": _public_step_results(getattr(run, "step_results", None)),
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


def _sanitize_governance_payload(value: Any, *, max_text_chars: int = 300) -> Any:
    """递归脱敏和截断治理审计载荷。"""

    value = redact_secrets(value)
    if isinstance(value, str):
        return value[:max_text_chars]
    if isinstance(value, dict):
        return {str(key)[:80]: _sanitize_governance_payload(item, max_text_chars=max_text_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_governance_payload(item, max_text_chars=max_text_chars) for item in value[:20]]
    if isinstance(value, tuple):
        return [_sanitize_governance_payload(item, max_text_chars=max_text_chars) for item in value[:20]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_text_chars]




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

    async def record_governance_event(
        self,
        run_id: str,
        *,
        user_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """持久化工具或 Guardrails 的最小审计事件。

        只接收摘要载荷，避免把原始简历、JD、模型输出或密钥写入可重放事件流。
        不存在的 run、跨用户 run 或非治理事件会被拒绝，调用方可将审计失败视作
        非业务失败，以免影响已完成的工具动作。
        """

        if not event_type.startswith(("tool.", "guardrail.")):
            raise ValueError("governance event_type must start with tool. or guardrail.")

        async with UnitOfWork(async_session) as uow:
            session = uow.db
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.user_id != user_id:
                return False

            await self._append_event(
                session,
                run,
                event_type,
                _sanitize_governance_payload(payload or {}),
            )
            run.updated_at = _now()
        return True

    async def record_observation(
        self,
        run_id: str,
        *,
        observation_id: str | None = None,
        trace_id: str | None = None,
        model_events: list[dict[str, Any]] | None = None,
    ) -> None:
        """Persist a Trace link and credential-free model metrics without blocking the run.

        ``observation_id`` is always local and supports idempotent writes. ``trace_id``
        is stored on the AgentRun only when Langfuse actually created the trace.
        """
        async with UnitOfWork(async_session) as uow:
            session = uow.db
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run:
                return

            if trace_id:
                run.trace_id = trace_id
            run.updated_at = _now()
            if not model_events:
                return
            observation_id = observation_id or trace_id or f"legacy:{run_id}"
            existing = await session.scalar(
                select(func.count(ModelMetricEventModel.id)).where(
                    ModelMetricEventModel.run_id == run_id,
                    ModelMetricEventModel.observation_id == observation_id,
                )
            )
            if existing:
                return
            now = _now()
            for event_index, event in enumerate(model_events):
                payload = _sanitize_governance_payload(event)
                event_type = str(payload.get("event_type") or "unknown")
                is_degradation = (
                    event_type in {"llm.request.failed", "llm.request.skipped"}
                    or int(payload.get("fallback_index") or 0) > 0
                    or bool(payload.get("authoritative_source_truncated"))
                    or bool(payload.get("truncated_sources"))
                )
                session.add(ModelMetricEventModel(
                    user_id=run.user_id,
                    run_id=run.id,
                    observation_id=observation_id,
                    trace_id=trace_id,
                    event_index=event_index,
                    agent_name=str(payload.get("agent_name") or run.agent_name or "unknown"),
                    task_type=run.task_type,
                    stage=str(payload.get("stage") or run.stage)[:160],
                    event_type=event_type[:160],
                    is_degradation=is_degradation,
                    payload=payload,
                    created_at=now,
                ))

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
                id=str(uuid.uuid4()), user_id=user_id, session_id=session_id, task_type=task_type,
                agent_name=definition.name, agent_version=definition.version, status="queued", stage="queued",
                idempotency_key=idempotency_key, payload_encrypted=encrypt_payload(payload), result=None,
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
        """Create an immediately running AgentRun without publishing an outbox task.

        Interactive HTTP workflows use this path after their user-input gate has
        completed.  The encrypted payload contains only a resumable reference,
        while lifecycle events and step results remain visible in Run Center.
        """
        if task_type not in TASK_DEFINITIONS:
            raise ValueError(f"unknown task type: {task_type}")
        definition = get_agent_definition(task_type)
        valid_stages = [step_id for step_id, _title in definition.steps]
        if initial_stage not in valid_stages or initial_stage == "queued":
            raise ValueError(f"invalid initial stage for {task_type}: {initial_stage}")

        async with async_session() as session:
            existing = await session.scalar(select(AgentRunModel).where(
                AgentRunModel.user_id == user_id,
                AgentRunModel.task_type == task_type,
                AgentRunModel.idempotency_key == idempotency_key,
            ))
            if existing:
                return existing, False

            now = _now()
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
                payload_encrypted=encrypt_payload(payload),
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

    async def _attach_owned_session_titles(
        self,
        session: AsyncSession,
        runs: list[AgentRunModel],
        user_id: str,
    ) -> None:
        """Attach owner-scoped interview-session display summaries in one query.

        AgentRun status describes one background execution, not the lifecycle of
        the linked interview.  The extra session fields let clients distinguish a
        completed turn-generation task from a completed interview without reading
        or decrypting the task payload.
        """
        session_ids = {run.session_id for run in runs if run.session_id}
        if not session_ids:
            return
        rows = await session.execute(
            select(
                SessionModel.session_id,
                SessionModel.title,
                SessionModel.status,
                SessionModel.question_count,
                SessionModel.max_questions,
            ).where(
                SessionModel.user_id == user_id,
                SessionModel.session_id.in_(session_ids),
            )
        )
        summaries = {row.session_id: row for row in rows}
        for run in runs:
            summary = summaries.get(run.session_id)
            setattr(run, "session_title", summary.title if summary else None)
            setattr(run, "session_status", summary.status if summary else None)
            setattr(run, "session_question_count", summary.question_count if summary else None)
            setattr(run, "session_max_questions", summary.max_questions if summary else None)

    async def get_task_type_for_worker(self, run_id: str) -> str | None:
        """Read only the task type needed to select an execution concurrency gate."""
        async with async_session() as session:
            return await session.scalar(
                select(AgentRunModel.task_type).where(AgentRunModel.id == run_id)
            )

    async def get(self, run_id: str, user_id: str) -> AgentRunModel | None:
        """获取单个 AgentRun（带用户归属校验）。"""
        async with async_session() as session:
            run = await session.scalar(select(AgentRunModel).where(AgentRunModel.id == run_id, AgentRunModel.user_id == user_id))
            if run:
                await self._attach_owned_session_titles(session, [run], user_id)
            return run

    async def list_runs(
        self,
        user_id: str,
        *,
        status: str | None = None,
        task_type: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AgentRunModel], int]:
        """List owner-scoped AgentRuns with optional status, task, and session filters.

        Current AgentRuns always persist their session link at creation time, so
        list reads never decrypt task payloads.
        """
        async with async_session() as session:
            filters = [AgentRunModel.user_id == user_id]
            if status:
                filters.append(AgentRunModel.status == status)
            if task_type:
                filters.append(AgentRunModel.task_type == task_type)
            if session_id:
                filters.append(AgentRunModel.session_id == session_id)
            rows = await session.scalars(
                select(AgentRunModel)
                .where(*filters)
                .order_by(AgentRunModel.created_at.desc(), AgentRunModel.id.desc())
                .limit(limit)
                .offset(offset)
            )
            total = await session.scalar(select(func.count(AgentRunModel.id)).where(*filters))
            runs = list(rows)
            await self._attach_owned_session_titles(session, runs, user_id)
            return runs, int(total or 0)

    async def summarize_runs(self, user_id: str) -> dict[str, int]:
        """Return exact whole-history lifecycle counts for one owner's AgentRuns.

        This aggregate intentionally has no UI filter or pagination input, so the
        Run Center never reports a page-sized number as an active or historical total.
        """
        async with async_session() as session:
            rows = await session.execute(
                select(AgentRunModel.status, func.count(AgentRunModel.id))
                .where(AgentRunModel.user_id == user_id)
                .group_by(AgentRunModel.status)
            )
            by_status = {status: int(count) for status, count in rows}
        return {
            "active": sum(by_status.get(status, 0) for status in ACTIVE_STATUSES),
            "history": sum(by_status.get(status, 0) for status in TERMINAL_STATUSES),
            "succeeded": by_status.get("succeeded", 0),
            "failed": by_status.get("failed", 0),
        }

    async def list_grouped_runs(
        self,
        user_id: str,
        *,
        status: str | None = None,
        task_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[str, list[AgentRunModel]]], list[AgentRunModel], int]:
        """List matching runs in pages of interview sessions, plus unassociated runs.

        Status and task-type predicates apply before session IDs are selected, so a
        returned session contains every one of its matching child runs rather than
        a page-sized subset.  Session titles are resolved separately through the
        owner-scoped session lookup and never from encrypted task payloads.
        """
        filters = [AgentRunModel.user_id == user_id]
        if status:
            filters.append(AgentRunModel.status == status)
        if task_type:
            filters.append(AgentRunModel.task_type == task_type)

        async with async_session() as session:
            associated_filters = [*filters, AgentRunModel.session_id.is_not(None)]
            session_rows = (
                await session.execute(
                    select(
                        AgentRunModel.session_id,
                        func.max(AgentRunModel.created_at).label("latest_created_at"),
                    )
                    .where(*associated_filters)
                    .group_by(AgentRunModel.session_id)
                    .order_by(func.max(AgentRunModel.created_at).desc(), AgentRunModel.session_id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            session_ids = [row.session_id for row in session_rows]
            session_total = await session.scalar(
                select(func.count(func.distinct(AgentRunModel.session_id))).where(*associated_filters)
            )

            runs_by_session: dict[str, list[AgentRunModel]] = {session_id: [] for session_id in session_ids}
            if session_ids:
                associated_runs = list(
                    await session.scalars(
                        select(AgentRunModel)
                        .where(*filters, AgentRunModel.session_id.in_(session_ids))
                        .order_by(AgentRunModel.created_at.desc(), AgentRunModel.id.desc())
                    )
                )
                for run in associated_runs:
                    if run.session_id is not None:
                        runs_by_session[run.session_id].append(run)

            other_runs = list(
                await session.scalars(
                    select(AgentRunModel)
                    .where(*filters, AgentRunModel.session_id.is_(None))
                    .order_by(AgentRunModel.created_at.desc(), AgentRunModel.id.desc())
                )
            )
            all_runs = [run for runs in runs_by_session.values() for run in runs] + other_runs
            await self._attach_owned_session_titles(session, all_runs, user_id)
            return (
                [(session_id, runs_by_session[session_id]) for session_id in session_ids],
                other_runs,
                int(session_total or 0),
            )

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
            return run, decrypt_payload(run.payload_encrypted)

    async def mark_stage(self, run_id: str, stage: str) -> None:
        """推进运行阶段并持久化步骤完成记录，不写入敏感任务载荷或模型原文。"""
        async with async_session() as session:
            run = await session.get(AgentRunModel, run_id, with_for_update=True)
            if not run or run.status != "running":
                return
            valid_stages = {item[0] for item in get_task_definition(run.task_type)["steps"]}
            if stage not in valid_stages:
                raise ValueError(f"invalid stage for {run.task_type}: {stage}")
            if run.stage == stage:
                return
            now = _now()
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
        async with async_session() as session:
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
            now = _now()
            step_results = dict(run.step_results or {})
            step = dict(step_results.get(stage) or {})
            step["checkpoint_encrypted"] = encrypt_payload(checkpoint)
            step["checkpoint_updated_at"] = now.isoformat()
            step_results[stage] = step
            run.step_results = step_results
            run.updated_at = now
            item_count = len(checkpoint.get("items") or []) if isinstance(checkpoint, dict) else 0
            await self._append_event(session, run, "run.checkpoint.saved", {"item_count": item_count})
            await session.commit()

    async def load_checkpoint(self, run_id: str, user_id: str, stage: str) -> dict[str, Any] | None:
        """按 owner 读取并解密恢复 checkpoint；密文不存在时返回 None。"""
        async with async_session() as session:
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
            value = decrypt_payload(encrypted)
            return value if isinstance(value, dict) else None

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
