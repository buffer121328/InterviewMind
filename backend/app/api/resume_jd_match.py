"""JD match analysis routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user_id
from app.schemas.jd_schemas import (
    JDMatchDetailResponse,
    JDMatchHistoryResponse,
    JDMatchRequest,
    JDMatchResponse,
)
from app.workflows.resume.jd_match import JDMatchBadRequest, JDMatchNotFound, jd_match_use_cases

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/jd-match", response_model=JDMatchResponse)
async def jd_match_endpoint(
    request: JDMatchRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Analyze how well a resume matches a target job description."""
    try:
        return await jd_match_use_cases.analyze(request=request, user_id=user_id)
    except JDMatchBadRequest as exc:
        raise HTTPException(status_code=400, detail={"message": exc.message}) from exc
    except Exception as exc:
        logger.error("JD 匹配分析失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"分析失败: {exc}") from exc


@router.get("/jd-match", response_model=JDMatchHistoryResponse)
async def list_jd_match_results(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
):
    """List JD match analysis results."""
    return await jd_match_use_cases.list_results(user_id=user_id, limit=limit)


@router.get("/jd-match/{analysis_id}", response_model=JDMatchDetailResponse)
async def get_jd_match_result(
    analysis_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """Get one JD match analysis result."""
    try:
        return await jd_match_use_cases.get_result(analysis_id=analysis_id, user_id=user_id)
    except JDMatchNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取 JD 分析结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/jd-match/{analysis_id}")
async def delete_jd_match_result(
    analysis_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """Delete one JD match analysis result."""
    try:
        return await jd_match_use_cases.delete_result(analysis_id=analysis_id, user_id=user_id)
    except JDMatchNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除 JD 分析结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
