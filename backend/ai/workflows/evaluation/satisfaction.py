"""用户满意度反馈用例:幂等提交与全量聚合统计。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.evaluation.user_feedback_repository import stats, submit
from app.schemas.satisfaction_schemas import (
    SatisfactionStatsResponse,
    SatisfactionSubmitResponse,
)


class SatisfactionUseCases:
    """满意度提交与统计应用服务,经会话依赖透传持久化。"""

    async def submit(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        agent_type: str,
        ref_key: str,
        rating: int | None,
        satisfied_aspects: list[str],
        dissatisfied_aspects: list[str],
        comment: str | None,
    ) -> SatisfactionSubmitResponse:
        """幂等提交反馈;created=False 表示该用户该任务实例已有记录。"""

        record, created = await submit(
            session,
            user_id=user_id,
            agent_type=agent_type,
            ref_key=ref_key,
            rating=rating,
            satisfied_aspects=satisfied_aspects,
            dissatisfied_aspects=dissatisfied_aspects,
            comment=comment,
        )
        return SatisfactionSubmitResponse(id=record.id, created=created)

    async def stats(self, session: AsyncSession) -> SatisfactionStatsResponse:
        """返回满意度全量聚合统计,不含可识别个体信息。"""

        return SatisfactionStatsResponse(**(await stats(session)))


satisfaction_use_cases = SatisfactionUseCases()
