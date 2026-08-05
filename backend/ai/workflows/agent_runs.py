"""Agent run application use cases for HTTP routes."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any

from app.domain.agent_runs import (
    TASK_TYPE_ABILITY_PROFILE,
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_JOB_RECOMMENDATION_CAPTURE,
    TASK_TYPE_RESUME_OPTIMIZE,
    TASK_TYPE_RESUME_WORKSPACE,
    TERMINAL_STATUSES,
)
from app.domain.agent_definitions import get_agent_definition
from ai.runtime.agent_runs.dispatcher import enqueue_agent_run
from ai.runtime.agent_runs.event_stream import replay_cursor
from ai.workflows.agent_tasks.registry import execute_registered_task
from ai.workflows.agent_tasks.types import DeferredExecutionResult
from ai.workflows.agent_tasks.interview_start import execute_interview_start
from ai.runtime.agent_runs.outbox import dispatch_pending_outbox
from app.db.repositories.session.session_repo import SessionRepo
from app.security.payload_crypto import TaskPayloadConfigurationError
from ai.runtime.agent_runs.service import (
    AgentRunService,
    first_running_stage,
    serialize_event,
    serialize_run,
    task_queue_enabled,
)
from ai.runtime.runtime_gate import get_run_gate

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentRunResponse:
    """HTTP-neutral AgentRun response."""

    payload: dict[str, Any]
    status_code: int = 200


@dataclass(slots=True)
class AgentRunUseCaseError(Exception):
    """AgentRun use-case failure."""

    message: str
    status_code: int = 400


class AgentRunConflict(AgentRunUseCaseError):
    """AgentRun cannot be changed in its current state."""


class AgentRunNotFound(AgentRunUseCaseError):
    """AgentRun is missing or hidden from this user."""


class AgentRunUnavailable(AgentRunUseCaseError):
    """AgentRun backend is temporarily unavailable."""


class AgentRunUseCases:
    """Create, list, mutate and stream resumable AgentRun tasks."""

    def __init__(self) -> None:
        """初始化 AgentRun 用例服务及其仓储/调度依赖；路由层只通过该服务访问任务生命周期。"""
        self._service = AgentRunService()
        self._session_repo = SessionRepo()

    async def _ensure_owned_existing_session(self, session_id: str, user_id: str) -> bool:
        """Return whether a session exists and belongs to the requesting user."""
        return await self._session_repo.get_session(session_id, user_id=user_id) is not None

    async def create_interview_start(
        self,
        *,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        """Create or execute an interview-start task."""
        if await self._session_repo.get_session(payload["thread_id"]) is not None:
            if not await self._ensure_owned_existing_session(payload["thread_id"], user_id):
                raise AgentRunNotFound("会话不存在或无权访问", status_code=404)
        if not task_queue_enabled():
            lease = await get_run_gate().acquire()
            if lease is None:
                raise AgentRunConflict("当前仍有面试任务在生成，请稍后重试", status_code=409)
            try:
                result = await execute_interview_start(payload, user_id)
                return AgentRunResponse(
                    payload={
                        "task_type": TASK_TYPE_INTERVIEW_START,
                        "status": "succeeded",
                        "result": result,
                    }
                )
            finally:
                await lease.release()
        return await self.create_queued_run(
            task_type=TASK_TYPE_INTERVIEW_START,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
            session_id=payload["thread_id"],
        )

    async def create_resume_optimize(
        self,
        *,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        """Create a resume-optimization task."""
        return await self.create_queued_run(
            task_type=TASK_TYPE_RESUME_OPTIMIZE,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_resume_workspace(
        self,
        *,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        """Create a workspace run after owner-scoping every referenced interview session.

        The executor repeats owner-scoped reads as a defense in depth measure, while
        this boundary rejects inaccessible session references before encrypting and
        enqueueing the sensitive resume payload.
        """
        for session_id in payload.get("session_ids") or []:
            if not await self._ensure_owned_existing_session(session_id, user_id):
                raise AgentRunNotFound("会话不存在或无权访问", status_code=404)
        return await self.create_queued_run(
            task_type=TASK_TYPE_RESUME_WORKSPACE,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_ability_profile(
        self,
        *,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        """Create one explicit owner-scoped ability-profile run."""
        return await self.create_queued_run(
            task_type=TASK_TYPE_ABILITY_PROFILE,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_interview_report(
        self,
        *,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        """Create an interview-report task."""
        if not await self._ensure_owned_existing_session(payload["session_id"], user_id):
            raise AgentRunNotFound("会话不存在或无权访问", status_code=404)
        return await self.create_queued_run(
            task_type=TASK_TYPE_INTERVIEW_REPORT,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
            session_id=payload["session_id"],
        )

    async def create_job_assets(
        self,
        *,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        """Create a job-assets task."""
        return await self.create_queued_run(
            task_type=TASK_TYPE_JOB_ASSETS,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_job_recommendation_capture(
        self,
        *,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        """Create a recoverable BOSS DOM import after enforcing user-scoped pacing."""
        from integrations.browser_automation.rate_limiter import (
            RateLimitType,
            check_rate,
        )

        can_proceed, message = await check_rate(user_id, RateLimitType.BOSS_CAPTURE)
        if not can_proceed:
            raise AgentRunConflict(message, status_code=429)
        return await self.create_queued_run(
            task_type=TASK_TYPE_JOB_RECOMMENDATION_CAPTURE,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_queued_run(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
        session_id: str | None = None,
        enqueue_fn: Callable[..., Any] | None = None,
    ) -> AgentRunResponse:
        """Create an AgentRun, executing inline when the queue is disabled."""
        if not task_queue_enabled():
            lease = await get_run_gate().acquire()
            if lease is None:
                raise AgentRunConflict("当前仍有任务在执行，请稍后重试", status_code=409)
            try:
                try:
                    run, created = await self._service.create_inline_or_get(
                        user_id=user_id,
                        payload=payload,
                        idempotency_key=idempotency_key,
                        task_type=task_type,
                        initial_stage=first_running_stage(task_type),
                        session_id=session_id,
                    )
                except TaskPayloadConfigurationError as exc:
                    raise AgentRunUnavailable(str(exc), status_code=503) from exc

                if not created:
                    if run.status in TERMINAL_STATUSES:
                        return AgentRunResponse(payload=serialize_run(run))
                    raise AgentRunConflict("同一任务正在执行，请稍后查看任务中心", status_code=409)

                async def progress(stage: str) -> None:
                    """Persist inline progress exactly like the queue worker path."""
                    await self._service.mark_stage(run.id, stage)

                execution_payload = {**payload, "_agent_run_id": run.id}
                try:
                    result = await execute_registered_task(task_type, execution_payload, user_id, progress)
                    if isinstance(result, DeferredExecutionResult):
                        await self._service.succeed_with_result_writer(run.id, result.persist)
                    else:
                        await self._service.succeed(run.id, result)
                except Exception as exc:
                    await self._service.fail(run.id, str(exc))
                    raise

                completed = await self._service.get(run.id, user_id)
                return AgentRunResponse(payload=serialize_run(completed or run))
            finally:
                await lease.release()

        if enqueue_fn is None:
            enqueue_fn = enqueue_agent_run

        try:
            run, created = await self._service.create_or_get(
                user_id=user_id,
                payload=payload,
                idempotency_key=idempotency_key,
                task_type=task_type,
                session_id=session_id,
            )
        except TaskPayloadConfigurationError as exc:
            raise AgentRunUnavailable(str(exc), status_code=503) from exc

        if created or run.status == "retrying":
            success, failed = await dispatch_pending_outbox(limit=50, enqueue_fn=enqueue_fn)
            if failed:
                logger.warning(
                    "AgentRun Outbox 即时投递失败，等待后台重试: success=%s failed=%s",
                    success,
                    failed,
                )
        return AgentRunResponse(payload=serialize_run(run), status_code=202)

    async def list_runs(
        self,
        *,
        user_id: str,
        status: str | None,
        task_type: str | None,
        limit: int,
        offset: int,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """List AgentRuns for one user, optionally narrowed to one owned session."""
        if task_type:
            try:
                get_agent_definition(task_type)
            except KeyError as exc:
                raise AgentRunUseCaseError("未知任务类型", status_code=400) from exc
        recovered = await self._service.recover_stale_runs(user_id)
        if recovered:
            success, failed = await dispatch_pending_outbox(limit=200, enqueue_fn=enqueue_agent_run)
            if failed:
                logger.warning(
                    "用户触发 AgentRun Outbox 恢复投递失败，等待后台重试: success=%s failed=%s",
                    success,
                    failed,
                )
        runs, total = await self._service.list_runs(
            user_id,
            status=status,
            task_type=task_type,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "runs": [serialize_run(run) for run in runs],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def summarize_runs(self, *, user_id: str) -> dict[str, int]:
        """Return unfiltered lifecycle totals for the authenticated user's task history."""
        return await self._service.summarize_runs(user_id)

    async def list_grouped_runs(
        self,
        *,
        user_id: str,
        status: str | None,
        task_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        """List runs grouped by session, with pagination applied to session groups.

        Response shape: ``groups`` contains zero or more ``session`` groups and,
        when matching unassociated runs exist, one ``other`` group. ``total`` and
        ``session_total`` count session groups (the paginated resource), while
        ``other_total`` counts all matching unassociated child runs.
        """
        if task_type:
            try:
                get_agent_definition(task_type)
            except KeyError as exc:
                raise AgentRunUseCaseError("未知任务类型", status_code=400) from exc
        recovered = await self._service.recover_stale_runs(user_id)
        if recovered:
            success, failed = await dispatch_pending_outbox(limit=200, enqueue_fn=enqueue_agent_run)
            if failed:
                logger.warning(
                    "用户触发 AgentRun Outbox 恢复投递失败，等待后台重试: success=%s failed=%s",
                    success,
                    failed,
                )
        session_groups, other_runs, session_total = await self._service.list_grouped_runs(
            user_id,
            status=status,
            task_type=task_type,
            limit=limit,
            offset=offset,
        )
        groups = [
            {
                "group_type": "session",
                "session_id": session_id,
                "session_title": getattr(runs[0], "session_title", None) if runs else None,
                "runs": [serialize_run(run) for run in runs],
            }
            for session_id, runs in session_groups
        ]
        if other_runs:
            groups.append(
                {
                    "group_type": "other",
                    "session_id": None,
                    "session_title": None,
                    "runs": [serialize_run(run) for run in other_runs],
                }
            )
        return {
            "success": True,
            "groups": groups,
            "total": session_total,
            "session_total": session_total,
            "other_total": len(other_runs),
            "limit": limit,
            "offset": offset,
        }

    async def get_run(self, *, run_id: str, user_id: str) -> dict[str, Any]:
        """Get one AgentRun."""
        run = await self._service.get(run_id, user_id)
        if not run:
            raise AgentRunNotFound("任务不存在或无权访问", status_code=404)
        return serialize_run(run)

    async def cancel_run(self, *, run_id: str, user_id: str) -> dict[str, Any]:
        """Cancel one non-terminal AgentRun."""
        run = await self._service.cancel(run_id, user_id)
        if not run:
            raise AgentRunConflict("任务当前不可取消", status_code=409)
        return serialize_run(run)

    async def retry_run(self, *, run_id: str, user_id: str) -> AgentRunResponse:
        """Retry one retryable AgentRun."""
        run = await self._service.retry(run_id, user_id)
        if not run:
            raise AgentRunConflict("任务不可重试或已超过最大尝试次数", status_code=409)
        success, failed = await dispatch_pending_outbox(limit=50, enqueue_fn=enqueue_agent_run)
        if failed:
            logger.warning("AgentRun retry Outbox 即时投递失败，等待后台重试: success=%s failed=%s", success, failed)
        return AgentRunResponse(payload=serialize_run(run), status_code=202)

    async def list_events(
        self,
        *,
        run_id: str,
        user_id: str,
        after_sequence: int,
        limit: int,
    ) -> dict[str, Any]:
        """List AgentRun events."""
        events = await self._service.list_events(
            run_id,
            user_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        if events is None:
            raise AgentRunNotFound("任务不存在或无权访问", status_code=404)
        return {"events": [serialize_event(event) for event in events]}

    async def stream_events(
        self,
        *,
        run_id: str,
        user_id: str,
        after_sequence: int,
        last_event_id: str | None,
    ) -> AsyncGenerator[str, None]:
        """Open an AgentRun SSE stream after validating ownership."""
        run = await self._service.get(run_id, user_id)
        if not run:
            raise AgentRunNotFound("任务不存在或无权访问", status_code=404)

        cursor = replay_cursor(after_sequence=after_sequence, last_event_id=last_event_id)

        async def generate() -> AsyncGenerator[str, None]:
            """创建并调度异步 AgentRun，使用加密 payload 持久化敏感输入，返回可轮询的任务摘要。"""
            nonlocal cursor
            while True:
                events = await self._service.list_events(run_id, user_id, after_sequence=cursor, limit=200) or []
                for event in events:
                    data = serialize_event(event)
                    cursor = event.sequence
                    yield (
                        f"id: {event.sequence}\n"
                        f"event: {event.event_type}\n"
                        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    )
                latest = await self._service.get(run_id, user_id)
                if latest is None or (latest.status in TERMINAL_STATUSES and not events):
                    return
                await asyncio.sleep(1)

        return generate()


agent_run_use_cases = AgentRunUseCases()
