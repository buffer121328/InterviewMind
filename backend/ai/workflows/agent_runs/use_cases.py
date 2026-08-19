"""AgentRun 应用 facade：稳定 HTTP 语义与领域协作者组合。"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any

from ai.runtime.agent_runs.outbox import dispatch_pending_outbox
from ai.runtime.agent_runs.service import AgentRunService, task_queue_enabled
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
from app.domain.interview_report_modes import (
    build_authoritative_report_source_version,
    normalize_report_mode,
    scope_report_idempotency_key,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentRunResponse:
    """应用层返回 HTTP 响应体与状态映射，不暴露运行时持久化对象。"""

    body: dict[str, Any]  # 序列化后的运行或结果载荷，即 HTTP 响应体
    status_code: int = 200  # HTTP 状态码，默认 200


@dataclass(slots=True)
class AgentRunUseCaseError(Exception):
    """AgentRun facade 的稳定业务错误。"""

    message: str  # 面向调用方的错误描述
    status_code: int = 400  # HTTP 状态码，默认 400


class AgentRunConflict(AgentRunUseCaseError):
    """请求与现有运行状态冲突。"""


class AgentRunNotFound(AgentRunUseCaseError):
    """资源不存在或不属于当前 owner。"""


class AgentRunUnavailable(AgentRunUseCaseError):
    """运行配置不可用，通常不应重试为另一种语义。"""


class AgentRunUseCases:
    """组合 AgentRun 的命令、查询和事件协作者，保持既有公开调用签名。"""

    # 协作者（mutations/queries）经 facade 实例引用这些本模块定义的类型，避免循环导入
    AgentRunResponse = AgentRunResponse
    AgentRunConflict = AgentRunConflict
    AgentRunNotFound = AgentRunNotFound
    AgentRunUnavailable = AgentRunUnavailable

    def __init__(self) -> None:
        """注入运行时服务和会话仓储；路由只经此 facade 访问生命周期。"""
        self._service = AgentRunService()
        self._session_repo = SessionRepo()
        self._queries = AgentRunQueries(self)
        self._mutations = AgentRunMutations(self)

    @staticmethod
    def _log_outbox_failure(action: str, success: int, failed: int) -> None:
        """记录 Outbox 即时投递失败，等待后台重试。

        Args:
            action: 触发投递的动作名称。
            success: 成功投递数量。
            failed: 失败投递数量。
        """
        logger.warning(
            "AgentRun %s Outbox 即时投递失败，等待后台重试: success=%s failed=%s",
            action,
            success,
            failed,
        )

    @staticmethod
    def _validate_task_type(task_type: str) -> None:
        """校验任务类型已注册，未知类型抛出业务错误。

        Args:
            task_type: 待校验的任务类型键。
        """
        try:
            get_agent_definition(task_type)
        except KeyError as exc:
            # 未注册的任务类型收敛为稳定的 400 业务错误，不泄露 KeyError 内部细节
            raise AgentRunUseCaseError("未知任务类型", status_code=400) from exc

    async def _recover_and_dispatch(self, user_id: str, *, limit: int) -> None:
        """恢复该用户的陈旧运行，并把积压的 Outbox 消息重新投递。

        Args:
            user_id: 当前用户标识。
            limit: Outbox 本次投递上限。
        """
        # ① 恢复该用户卡在陈旧态的运行
        recovered = await self._service.recover_stale_runs(user_id)
        if not recovered:
            return
        # ② 有恢复才顺带即时投递积压的 Outbox 消息
        success, failed = await dispatch_pending_outbox(
            limit=limit,
            enqueue_fn=enqueue_agent_run,
        )
        # ③ 部分失败仅告警，交由后台定时重试兜底
        if failed:
            self._log_outbox_failure("恢复", success, failed)

    async def _ensure_owned_existing_session(self, session_id: str, user_id: str) -> bool:
        """确认会话存在时同时属于当前用户，避免跨 owner 创建关联运行。

        Args:
            session_id: 会话标识。
            user_id: 当前用户标识。
        """
        return await self._session_repo.get_session(session_id, user_id=user_id) is not None

    async def _run_inline_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        user_id: str,
        progress: ProgressCallback,
    ) -> ExecutionResult:
        """通过权威 Harness InlineDriver 执行请求内任务。

        Args:
            task_type: 任务类型键。
            payload: 任务载荷。
            user_id: 当前用户标识。
            progress: 进度回调，用于上报任务阶段。
        """
        # ① 提取会话 id：兼容 session_id/thread_id 两种键名，截断上限 200 防注入
        raw_session_id = payload.get("session_id") or payload.get("thread_id")
        session_id = str(raw_session_id)[:200] if raw_session_id else None
        # ② 内联任务可携带关联的 AgentRun id，用于进度回填
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
        """创建面试首题任务；无队列模式保留原同步兼容响应。

        Args:
            payload: 面试启动载荷，须含 `thread_id`。
            user_id: 当前用户标识。
            idempotency_key: 幂等键，用于复用已存在的运行。
        """
        if await self._session_repo.get_session(payload["thread_id"]) is not None:
            if not await self._ensure_owned_existing_session(payload["thread_id"], user_id):
                raise AgentRunNotFound("会话不存在或无权访问", status_code=404)
        if not task_queue_enabled():
            # ① 无队列模式：先抢占单用户运行门禁，防止并发重复生成
            lease = await get_run_gate().acquire()
            if lease is None:
                raise AgentRunConflict("当前仍有面试任务在生成，请稍后重试", status_code=409)
            try:
                # ② inline 执行不创建 AgentRun，进度回调给空实现以兼容 adapter 契约
                async def progress(_stage: str) -> None:
                    """同步兼容响应不创建 AgentRun，仅满足 adapter 进度契约。

                    Args:
                        _stage: 传入的 _stage 值。
                    """

                result = await self._run_inline_task(
                    TASK_TYPE_INTERVIEW_START,
                    payload,
                    user_id,
                    progress,
                )
                # ③ 同步路径直接返回执行结果，不进入队列
                return AgentRunResponse(
                    body={
                        "task_type": TASK_TYPE_INTERVIEW_START,
                        "status": "succeeded",
                        "result": result,
                    }
                )
            finally:
                # ④ 无论成败都释放门禁，避免死锁
                await lease.release()
        # 队列模式
        return await self.create_queued_run(
            task_type=TASK_TYPE_INTERVIEW_START,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
            session_id=payload["thread_id"],
        )

    async def create_resume_optimize(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """创建简历优化运行。

        Args:
            payload: 简历优化载荷。
            user_id: 当前用户标识。
            idempotency_key: 幂等键，用于复用已存在的运行。
        """
        return await self.create_queued_run(
            task_type=TASK_TYPE_RESUME_OPTIMIZE,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_resume_workspace(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """创建简历工作区运行，并验证引用的所有面试会话。

        Args:
            payload: 简历工作区载荷，含 `session_ids`。
            user_id: 当前用户标识。
            idempotency_key: 幂等键，用于复用已存在的运行。
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

    async def create_ability_profile(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """创建能力画像运行。

        Args:
            payload: 能力画像载荷。
            user_id: 当前用户标识。
            idempotency_key: 幂等键，用于复用已存在的运行。
        """
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
        idempotency_key: str | None,
    ) -> AgentRunResponse:
        """创建面试报告运行并保持 owner-scoped session 关联。

        Args:
            payload: 面试报告载荷，须含 `session_id`。
            user_id: 当前用户标识。
            idempotency_key: 幂等键，用于复用已存在的运行。
        """
        session_id = str(payload["session_id"])
        session = await self._session_repo.get_session(
            session_id,
            include_resume_content=True,
            user_id=user_id,
        )
        if session is None:
            raise AgentRunNotFound("会话不存在或无权访问", status_code=404)
        normalized_payload = dict(payload)
        report_mode = normalize_report_mode(normalized_payload.get("report_mode"))
        report_source_version = build_authoritative_report_source_version(session)
        normalized_payload["report_mode"] = report_mode.value
        normalized_payload["report_source_version"] = report_source_version

        # 只持久化可安全索引的模式和哈希版本；不把问答或简历正文写入 AgentRun 元数据。
        await self._session_repo.update_session(
            session_id=session_id,
            metadata_updates={
                "report_mode": report_mode.value,
                "report_source_version": report_source_version,
            },
            user_id=user_id,
        )
        return await self.create_queued_run(
            task_type=TASK_TYPE_INTERVIEW_REPORT,
            payload=normalized_payload,
            user_id=user_id,
            idempotency_key=scope_report_idempotency_key(
                idempotency_key,
                session_id=session_id,
                report_mode=report_mode,
                source_version=report_source_version,
            ),
            session_id=session_id,
        )

    async def create_job_assets(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """创建岗位资产运行。

        Args:
            payload: 岗位资产载荷。
            user_id: 当前用户标识。
            idempotency_key: 幂等键，用于复用已存在的运行。
        """
        return await self.create_queued_run(
            task_type=TASK_TYPE_JOB_ASSETS,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def create_job_recommendation_capture(self, *, payload: dict[str, Any], user_id: str, idempotency_key: str) -> AgentRunResponse:
        """在 BOSS 捕获频率门限后创建岗位推荐采集运行。

        Args:
            payload: 岗位推荐采集载荷。
            user_id: 当前用户标识。
            idempotency_key: 幂等键，用于复用已存在的运行。
        """
        from integrations.browser_automation.rate_limiter import RateLimitType, check_rate

        # 受 BOSS 采集频率门限约束：超频直接 429 拒绝，不创建运行
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
        """委托写入协作者创建队列或 inline 运行，保持原公开入口。

        Args:
            task_type: 任务类型键。
            payload: 任务载荷。
            user_id: 当前用户标识。
            idempotency_key: 幂等键，用于复用已存在的运行。
            session_id: 关联会话标识，可选。
            enqueue_fn: 自定义入队函数，可选。
        """
        return await self._mutations.create_queued_run(
            task_type=task_type,
            payload=payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
            session_id=session_id,
            enqueue_fn=enqueue_fn,
        )

    async def list_runs(self, **kwargs: Any) -> dict[str, Any]:
        """列出当前 owner 可见的运行。

        Args:
            kwargs: 透传给 AgentRunQueries.list_runs 的筛选与分页参数。
        """
        return await self._queries.list_runs(**kwargs)

    async def summarize_runs(self, *, user_id: str) -> dict[str, int]:
        """汇总当前 owner 的运行状态。

        Args:
            user_id: 当前用户标识。
        """
        return await self._queries.summarize_runs(user_id=user_id)

    async def list_grouped_runs(self, **kwargs: Any) -> dict[str, Any]:
        """按会话分组列出当前 owner 的运行。

        Args:
            kwargs: 透传给 AgentRunQueries.list_grouped_runs 的筛选与分页参数。
        """
        return await self._queries.list_grouped_runs(**kwargs)

    async def get_run(self, *, run_id: str, user_id: str) -> dict[str, Any]:
        """读取一个 owner-scoped 运行。

        Args:
            run_id: 目标 AgentRun 标识。
            user_id: 当前用户标识。
        """
        return await self._queries.get_run(run_id=run_id, user_id=user_id)

    async def cancel_run(self, *, run_id: str, user_id: str) -> dict[str, Any]:
        """取消当前 owner 可取消的运行。

        Args:
            run_id: 目标 AgentRun 标识。
            user_id: 当前用户标识。
        """
        return await self._mutations.cancel_run(run_id=run_id, user_id=user_id)

    async def retry_run(self, *, run_id: str, user_id: str) -> AgentRunResponse:
        """重试当前 owner 可重试的运行。

        Args:
            run_id: 目标 AgentRun 标识。
            user_id: 当前用户标识。
        """
        return await self._mutations.retry_run(run_id=run_id, user_id=user_id)

    async def list_events(self, **kwargs: Any) -> dict[str, Any]:
        """读取当前 owner 的可重放数据库事件。

        Args:
            kwargs: 透传给 AgentRunQueries.list_events 的分页与游标参数。
        """
        return await self._queries.list_events(**kwargs)

    async def stream_events(
        self,
        *,
        run_id: str,
        user_id: str,
        after_sequence: int,
        last_event_id: str | None,
    ) -> AsyncGenerator[str, None]:
        """验证 owner 后投影稳定的 AgentRun SSE 事件。

        Args:
            run_id: 目标 AgentRun 标识。
            user_id: 当前用户标识。
            after_sequence: 已投影到的最大事件序号，初始为 0。
            last_event_id: SSE Last-Event-ID，用于断线续传对齐。
        """
        # ① owner 校验：运行存在且归属当前用户，才允许投影事件流
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
