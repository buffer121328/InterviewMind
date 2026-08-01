"""用户满意度反馈 HTTP API。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai.workflows.evaluation.satisfaction import satisfaction_use_cases
from app.api.deps import get_current_user_id
from app.db.models.base import get_session
from app.schemas.satisfaction_schemas import (
    SatisfactionStatsResponse,
    SatisfactionSubmitRequest,
    SatisfactionSubmitResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["满意度反馈"])


@router.post("/satisfaction", response_model=SatisfactionSubmitResponse)
async def submit_satisfaction(
    request: SatisfactionSubmitRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SatisfactionSubmitResponse:
    """提交一次用户满意度反馈;同一用户同一任务实例重复提交幂等命中既有记录。"""

    return await satisfaction_use_cases.submit(
        session,
        user_id=user_id,
        agent_type=request.agent_type,
        ref_key=request.ref_key,
        rating=request.rating,
        satisfied_aspects=request.satisfied_aspects,
        dissatisfied_aspects=request.dissatisfied_aspects,
        comment=request.comment,
    )


@router.get("/satisfaction/stats", response_model=SatisfactionStatsResponse)
async def get_satisfaction_stats(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SatisfactionStatsResponse:
    """返回满意度全量聚合统计,不含可识别个体信息。"""

    return await satisfaction_use_cases.stats(session)
