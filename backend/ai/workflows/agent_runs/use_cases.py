"""AgentRun 应用 facade：稳定 HTTP 语义与领域协作者组合。"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any

from ai.runtime.agent_runs.outbox import dispatch_pending_outbox
from ai.runtime.agent_runs.service import (
    AgentRunService,
    first_running_stage,
    serialize_event,
    serialize_run,
    task_queue_enabled,
)
from ai.runtime.execution.gate import get_run_gate
from ai.workflows.agent_runs.catalog import get_inline_driver
from ai.workflows.agent_runs.contracts import ExecutionResult, ProgressCallback
from ai.workflows.agent_runs.events import stream_event_sse
from ai.workflows.agent_runs.mutations import AgentRunMutations
from ai.workflows.agent_runs.queries import AgentRunQueries
from ai.workflows.agent_runs.queue.submission import enqueue_agent_run
from app.db.repositories.session.session_repo import SessionRepo
from app.domain.agent_definitions import get_agent_definition
from app.domain.agent_runs import (
    TASK_TYPE_ABILITY_PROFILE,
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_JOB_ASSETS,
    TASK_TYPE_JOB_RECOMMENDATION_CAPTURE,
    TASK_TYPE_RESUME_OPTIMIZE,
    TASK_TYPE_RESUME_WORKSPACE,
)
from app.security.payload_crypto import TaskPayloadConfigurationError
from app.security.security import safe_error_message

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentRunResponse:
    """应用层返回 payload 与 HTTP 状态映射，不暴露运行时持久化对象。"""

    payload: dict[str, Any]
    status_code: int = 200


@dataclass(slots=True)
class AgentRunUseCaseError(Exception):
    """AgentRun facade 的稳定业务错误。"""

    message: str
    status_code: int = 400


class AgentRunConflict(AgentRunUseCaseError):
    """请求与现有运行状态冲突。"""


class AgentRunNotFound(AgentRunUseCaseError):
    """资源不存在或不属于当前 owner。"""


class AgentRunUnavailable(AgentRunUseCaseError):
    """运行配置不可用，通常不应重试为另一种语义。"""


class AgentRunUseCases:
    """组合 AgentRun 的命令、查询和事件协作者，保持既有公开调用签名。"""

    AgentRunResponse = AgentRunResponse
    AgentRunConflict = AgentRunConflict
    AgentRunNotFound = AgentRunNotFound
    AgentRunUnavailable = AgentRunUnavailable
    _task_payload_configuration_error = TaskPayloadConfigurationError

    def __init__(self) -> None:
        """注入运行时服务和会话仓储；路由只经此 facade 访问生命周期。"""
        self._service = AgentRunService()
        self._session_repo = SessionRepo()
        self._queries = AgentRunQueries(self)
        self._mutations = AgentRunMutations(self)

    # Compatibility-aware narrow adapters: tests and configured integrations can
    # still patch these module seams, while collaborators never import this facade.
    @staticmethod
    def _serialize_run(run: Any) -> dict[str, Any]:
        return serialize_run(run)

    @staticmethod
    def _serialize_event(event: Any) -> dict[str, Any]:
        return serialize_event(event)

    @staticmethod
    def _task_queue_enabled() -> bool:
        return task_queue_enabled()

    @staticmethod
    def _get_run_gate() -> Any:
        return get_run_gate()

    @staticmethod
    def _get_agent_definition(task_type: str) -> Any:
        return get_agent_definition(task_type)

    @staticmethod
    def _first_running_stage(task_type: str) -> str:
        return first_running_stage(task_type)

    @staticmethod
    def _safe_error_message(error: Exception) -> str:
        return safe_error_message(error)

    @staticmethod
    def _enqueue_agent_run(run_id: str) -> None:
        enqueue_agent_run(run_id)

    @staticmethod
    async def _dispatch_pending_outbox(*, limit: int, enqueue_fn: Callable[..., Any]) -> tuple[int, int]:
        return await dispatch_pending_outbox(limit=limit, enqueue_fn=enqueue_fn)

    @staticmethod
    def _log_outbox_failure(action: str, success: int, failed: int) -> None:
        logger.warning(
            "AgentRun %s Outbox 即时投递失败，等待后台重试: success=%s failed=%s",
            action,
            success,
            failed,
        )

    @staticmethod
    def _validate_task_type(task_type: str) -> None:
        try:
            get_agent_definition(task_type)
        except KeyError as exc:
            raise AgentRunUseCaseError("未知任务类型", status_code=400) from exc

    async def _recover_and_dispatch(self, user_id: str, *, limit: int) -> None:
        recovered = await self._service.recover_stale_runs(user_id)
        if not recovered:
            return
        success, failed = await self._dispatch_pending_outbox(
            limit=limit,
            enqueue_fn=self._enqueue_agent_run,
        )
        if failed:
            self._log_outbox_failure("恢复", success, failed)

    async def _ensure_owned_existing_session(self, session_id: str, user_id: str) -> bool:
        """确认会话存在时同时属于当前用户，避免跨 owner 创建关联运行。"""
        return await self._session_repo.get_session(session_id, user_id=user_id) is not None

    async def _run_inline_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        user_id: str,
        progress: ProgressCallback,
    ) -> ExecutionResult:
        """通过权威 Harness InlineDriver 执行请求内任务。"""
        raw_session_id = payload.get("session_id") or payload.get("thread_id")
        session_id = str(raw_session_id)[:200] if raw_session_id else None
        run_id = str(payload.get("_agent_run_id") or "") or None
        return await get_inline_driver().run(
            task_type=task_type,
            payload=payload,
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            progress=progress,
        )

    async def create_interview_start(
        self,
        *,
        payload: dict[str, Any],
        user_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        """创建面试首题任务；无队列模式保留原同步兼容响应。"""
        if await self._session_repo.get_session(payload["thread_id"]) is not None:
            if not await self._ensure_owned_existing_session(payload["thread_id"], user_id):
                raise AgentRunNotFound("会话不存在或无权访问", status_code=404)
        if not self._task_queue_enabled():
            lease = await self._get_run_gate().acquire()
            if lease is None:
                raise AgentRunConflict("当前仍有面试任务在生成，请稍后重试", status_code=409)
            try:
                async def progress(_stage: str) -> None:
                    """同步兼容响应不创建 AgentRun，仅满足 adapter 进度契约。"""

                result = await self._run_inline_task(
                    TASK_TYPE_INTERVIEW_START,
                    payload,
                    user_id,
                    progress,
                )
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

    async def create_resume_optimize(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """创建简历优化运行。"""
        return await self.create_queued_run(
            task_type=TASK_TYPE_RESUME_OPTIMIZE,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_resume_workspace(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """创建简历工作区运行，并验证引用的所有面试会话。"""
        for session_id in payload.get("session_ids") or []:
            if not await self._ensure_owned_existing_session(session_id, user_id):
                raise AgentRunNotFound("会话不存在或无权访问", status_code=404)
        return await self.create_queued_run(
            task_type=TASK_TYPE_RESUME_WORKSPACE,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_ability_profile(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """创建能力画像运行。"""
        return await self.create_queued_run(
            task_type=TASK_TYPE_ABILITY_PROFILE,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_interview_report(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """创建面试报告运行并保持 owner-scoped session 关联。"""
        if not await self._ensure_owned_existing_session(payload["session_id"], user_id):
            raise AgentRunNotFound("会话不存在或无权访问", status_code=404)
        return await self.create_queued_run(
            task_type=TASK_TYPE_INTERVIEW_REPORT,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
            session_id=payload["session_id"],
        )

    async def create_job_assets(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """创建岗位资产运行。"""
        return await self.create_queued_run(
            task_type=TASK_TYPE_JOB_ASSETS,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_job_recommendation_capture(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """在 BOSS 捕获频率门限后创建岗位推荐采集运行。"""
        from integrations.browser_automation.rate_limiter import RateLimitType, check_rate

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
        """委托写入协作者创建队列或 inline 运行，保持原公开入口。"""
        return await self._mutations.create_queued_run(
            task_type=task_type,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
            session_id=session_id,
            enqueue_fn=enqueue_fn,
        )

    async def list_runs(self, **kwargs: Any) -> dict[str, Any]:
        """列出当前 owner 可见的运行。"""
        return await self._queries.list_runs(**kwargs)

    async def summarize_runs(self, *, user_id: str) -> dict[str, int]:
        """汇总当前 owner 的运行状态。"""
        return await self._queries.summarize_runs(user_id=user_id)

    async def list_grouped_runs(self, **kwargs: Any) -> dict[str, Any]:
        """按会话分组列出当前 owner 的运行。"""
        return await self._queries.list_grouped_runs(**kwargs)

    async def get_run(self, *, run_id: str, user_id: str) -> dict[str, Any]:
        """读取一个 owner-scoped 运行。"""
        return await self._queries.get_run(run_id=run_id, user_id=user_id)

    async def cancel_run(self, *, run_id: str, user_id: str) -> dict[str, Any]:
        """取消当前 owner 可取消的运行。"""
        return await self._mutations.cancel_run(run_id=run_id, user_id=user_id)

    async def retry_run(self, *, run_id: str, user_id: str) -> AgentRunResponse:
        """重试当前 owner 可重试的运行。"""
        return await self._mutations.retry_run(run_id=run_id, user_id=user_id)

    async def list_events(self, **kwargs: Any) -> dict[str, Any]:
        """读取当前 owner 的可重放数据库事件。"""
        return await self._queries.list_events(**kwargs)

    async def stream_events(
        self,
        *,
        run_id: str,
        user_id: str,
        after_sequence: int,
        last_event_id: str | None,
    ) -> AsyncGenerator[str, None]:
        """验证 owner 后投影稳定的 AgentRun SSE 事件。"""
        run = await self._service.get(run_id, user_id)
        if not run:
            raise AgentRunNotFound("任务不存在或无权访问", status_code=404)
        return stream_event_sse(
            service=self._service,
            run_id=run_id,
            user_id=user_id,
            after_sequence=after_sequence,
            last_event_id=last_event_id,
        )


agent_run_use_cases = AgentRunUseCases()
