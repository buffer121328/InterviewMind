from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from ai.runtime.agent_runs.outbox import enqueue_agent_run_outbox
from ai.runtime.agent_runs.settings import max_attempts, stale_after_seconds
from app.db.models import (
    AgentRunModel,
)
from app.domain.agent_runs import (
    ACTIVE_STATUSES,
)


class AgentRunRecoveryMixin:
    async def _recover(self, *, user_id: str | None, limit: int) -> list[AgentRunModel]:
            """恢复卡住的 AgentRun：处理取消请求、重新投递未领取或执行中断的任务。"""
            cutoff = self._runtime_now() - timedelta(seconds=stale_after_seconds())
            recovered: list[AgentRunModel] = []
            async with self._runtime_async_session() as session:
                filters = [AgentRunModel.status.in_(ACTIVE_STATUSES), AgentRunModel.updated_at < cutoff]
                if user_id is not None:
                    filters.append(AgentRunModel.user_id == user_id)
                rows = await session.scalars(select(AgentRunModel).where(*filters).order_by(AgentRunModel.updated_at).limit(limit).with_for_update(skip_locked=True))
                now = self._runtime_now()
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
