"""历史面试评测来源的 owner-scoped 查询。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InterviewQuestionAttemptModel, SessionModel


class InterviewHistoryRepositoryMixin:
    """为 EvaluationRepository 提供历史面试来源查询，不复用普通消息记录。"""

    async def list_interview_history_sessions(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        limit: int,
        offset: int,
        session_id: str | None = None,
    ) -> tuple[list[SessionModel], dict[str, list[InterviewQuestionAttemptModel]], int]:
        """分页列出 owner 的 completed sessions，并批量附加持久化 attempts。"""

        filters = [
            SessionModel.user_id == user_id,
            SessionModel.status == "completed",
        ]
        if session_id:
            filters.append(SessionModel.session_id == session_id)
        total = await session.scalar(
            select(func.count()).select_from(SessionModel).where(*filters)
        )
        sessions = list(
            await session.scalars(
                select(SessionModel)
                .where(*filters)
                .order_by(SessionModel.updated_at.desc(), SessionModel.session_id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        attempts_by_session: dict[str, list[InterviewQuestionAttemptModel]] = {
            row.session_id: [] for row in sessions
        }
        if sessions:
            attempts = list(
                await session.scalars(
                    select(InterviewQuestionAttemptModel)
                    .where(
                        InterviewQuestionAttemptModel.user_id == user_id,
                        InterviewQuestionAttemptModel.session_id.in_(attempts_by_session),
                    )
                    .order_by(
                        InterviewQuestionAttemptModel.session_id,
                        InterviewQuestionAttemptModel.sequence,
                        InterviewQuestionAttemptModel.id,
                    )
                )
            )
            for attempt in attempts:
                attempts_by_session.setdefault(attempt.session_id, []).append(attempt)
        return sessions, attempts_by_session, int(total or 0)

    async def get_interview_history_attempt(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        attempt_id: int,
    ) -> tuple[SessionModel, InterviewQuestionAttemptModel] | None:
        """按 owner 读取 attempt 与所属 session；跨 owner 统一返回不存在。"""

        row = (
            await session.execute(
                select(SessionModel, InterviewQuestionAttemptModel)
                .join(
                    InterviewQuestionAttemptModel,
                    InterviewQuestionAttemptModel.session_id == SessionModel.session_id,
                )
                .where(
                    SessionModel.user_id == user_id,
                    InterviewQuestionAttemptModel.user_id == user_id,
                    InterviewQuestionAttemptModel.id == attempt_id,
                )
            )
        ).one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def get_interview_history_attempts(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        attempt_ids: list[int],
    ) -> dict[int, tuple[SessionModel, InterviewQuestionAttemptModel]]:
        """批量读取选中 attempt，返回值按稳定 ID 映射且不泄露缺失归属。"""

        if not attempt_ids:
            return {}
        rows = await session.execute(
            select(SessionModel, InterviewQuestionAttemptModel)
            .join(
                InterviewQuestionAttemptModel,
                InterviewQuestionAttemptModel.session_id == SessionModel.session_id,
            )
            .where(
                SessionModel.user_id == user_id,
                InterviewQuestionAttemptModel.user_id == user_id,
                InterviewQuestionAttemptModel.id.in_(attempt_ids),
            )
        )
        return {int(attempt.id): (source_session, attempt) for source_session, attempt in rows.all()}
