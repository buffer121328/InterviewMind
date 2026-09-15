"""用户满意度反馈 HTTP API。"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ai.workflows.evaluation.satisfaction import satisfaction_use_cases
from app.api.deps import get_current_user_id
from app.db.models.base import get_session
from app.schemas.evaluation.satisfaction_schemas import (
    SatisfactionFeedbackItem,
    SatisfactionFeedbackListResponse,
    SatisfactionPromotionLinkRequest,
    SatisfactionPromotionRequest,
    SatisfactionReviewRequest,
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
    """提交一次用户满意度反馈;同一用户同一任务实例重复提交幂等命中既有记录。

    Args:
        request: 满意度提交请求体（agent_type、ref_key、rating 及可选意见）。
        user_id: 当前登录用户 ID，用于归属校验。
        session: 数据库异步会话。
    """

    try:
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
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/satisfaction/stats", response_model=SatisfactionStatsResponse)
async def get_satisfaction_stats(
    agent_type: str | None = Query(default=None, pattern="^(interview|resume_optimize)$"),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SatisfactionStatsResponse:
    """返回满意度全量聚合统计,不含可识别个体信息。

    Args:
        user_id: 当前登录用户 ID（鉴权）。
        session: 数据库异步会话。
    """

    return await satisfaction_use_cases.stats(
        session,
        user_id=user_id,
        agent_type=agent_type,
        created_from=created_from,
        created_to=created_to,
    )


@router.get("/satisfaction/feedback", response_model=SatisfactionFeedbackListResponse)
async def get_satisfaction_feedback(
    agent_type: str | None = Query(default=None, pattern="^(interview|resume_optimize)$"),
    review_status: str | None = Query(
        default=None, pattern="^(not_required|pending|resolved|promoted)$"
    ),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SatisfactionFeedbackListResponse:
    """返回当前用户的反馈明细和治理状态。"""

    return await satisfaction_use_cases.list(
        session,
        user_id=user_id,
        agent_type=agent_type,
        review_status=review_status,
        created_from=created_from,
        created_to=created_to,
        page=page,
        limit=limit,
    )


@router.post("/satisfaction/feedback/{feedback_id}/review", response_model=SatisfactionFeedbackItem)
async def review_satisfaction_feedback(
    feedback_id: str,
    request: SatisfactionReviewRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SatisfactionFeedbackItem:
    """完成人工复核；候选集提升仍须走独立确认入口。"""

    try:
        return await satisfaction_use_cases.resolve(
            session, user_id=user_id, feedback_id=feedback_id, note=request.note
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/satisfaction/feedback/{feedback_id}/promotion-link", response_model=SatisfactionFeedbackItem
)
async def link_satisfaction_feedback_promotion(
    feedback_id: str,
    request: SatisfactionPromotionLinkRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SatisfactionFeedbackItem:
    """Link a governed production-history dataset after the negative feedback is reviewed."""

    try:
        return await satisfaction_use_cases.link_promotion(
            session,
            user_id=user_id,
            feedback_id=feedback_id,
            dataset_id=request.dataset_id,
            capability=request.capability,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/satisfaction/feedback/{feedback_id}/promote", status_code=201)
async def promote_satisfaction_feedback(
    feedback_id: str,
    request: SatisfactionPromotionRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Atomically promote a reviewed negative feedback item through its source adapter."""

    try:
        return await satisfaction_use_cases.promote(
            session,
            user_id=user_id,
            feedback_id=feedback_id,
            capability=request.capability,
            confirmation=request.confirmation,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
