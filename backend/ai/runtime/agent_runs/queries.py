from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentRunEventModel,
    AgentRunModel,
    SessionModel,
)
from app.domain.agent_runs import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
)


class AgentRunQueriesMixin:
    async def _attach_owned_session_titles(
            self,
            session: AsyncSession,
            runs: list[AgentRunModel],
            user_id: str,
        ) -> None:
            """附加用户所属会话相关后端逻辑。"""
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
            """获取任务类型Worker相关后端逻辑。"""
            async with self._runtime_async_session() as session:
                return await session.scalar(
                    select(AgentRunModel.task_type).where(AgentRunModel.id == run_id)
                )

    async def get(self, run_id: str, user_id: str) -> AgentRunModel | None:
            """获取单个 AgentRun（带用户归属校验）。"""
            async with self._runtime_async_session() as session:
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
            """列出运行相关后端逻辑。"""
            async with self._runtime_async_session() as session:
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
            """汇总运行相关后端逻辑。"""
            async with self._runtime_async_session() as session:
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
            """列出分组运行相关后端逻辑。"""
            filters = [AgentRunModel.user_id == user_id]
            if status:
                filters.append(AgentRunModel.status == status)
            if task_type:
                filters.append(AgentRunModel.task_type == task_type)

            async with self._runtime_async_session() as session:
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
            async with self._runtime_async_session() as session:
                owned = await session.scalar(select(AgentRunModel.id).where(AgentRunModel.id == run_id, AgentRunModel.user_id == user_id))
                if not owned:
                    return None
                rows = await session.scalars(select(AgentRunEventModel).where(
                    AgentRunEventModel.run_id == run_id,
                    AgentRunEventModel.sequence > after_sequence,
                ).order_by(AgentRunEventModel.sequence).limit(limit))
                return list(rows)
