"""提供简历优化相关后端功能。"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user_id
from app.schemas.resume.resume_schemas import (
    ResumeAnalyzeRequest,
    ResumeAnalyzeResponse,
    ResumeOptimizeRequest,
    ResumeOptimizeResponse,
    ResumeReviewRequest,
    ResumeReviewResponse,
)
from ai.workflows.resume.optimization import (
    ResumeOptimizationBadRequest,
    ResumeOptimizationNotFound,
    ResumeReviewConflict,
    resume_optimization_use_cases,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/analyze", response_model=ResumeAnalyzeResponse)
async def analyze_resume_endpoint(
    request: ResumeAnalyzeRequest,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """分析简历并生成诊断报告。

    Args:
        request: 简历分析请求体（简历内容等）。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_optimization_use_cases.analyze_resume(request=request, user_id=user_id)
    except ResumeOptimizationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("简历分析失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"分析失败: {exc}") from exc


@router.post("/optimize", response_model=ResumeOptimizeResponse)
async def optimize_resume_endpoint(
    request: ResumeOptimizeRequest,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """对简历执行整体优化。

    Args:
        request: 简历优化请求体（简历与优化要求）。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_optimization_use_cases.optimize_resume(request=request, user_id=user_id)
    except ResumeOptimizationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        logger.error("简历优化失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"优化失败: {exc}") from exc


@router.get("/optimize/{result_id}/review", response_model=ResumeReviewResponse)
async def get_resume_review(
    result_id: int,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """获取简历优化结果的复核意见。

    Args:
        result_id: 优化结果 ID。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_optimization_use_cases.get_resume_review(result_id=result_id, user_id=user_id)
    except ResumeOptimizationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.post("/optimize/{result_id}/review", response_model=ResumeReviewResponse)
async def submit_resume_review(
    result_id: int,
    request: ResumeReviewRequest,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """提交对优化结果的复核意见。

    Args:
        result_id: 优化结果 ID。
        request: 复核请求体（同意/修改意见等）。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_optimization_use_cases.submit_resume_review(
            result_id=result_id,
            request=request,
            user_id=user_id,
        )
    except ResumeReviewConflict as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except ResumeOptimizationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ResumeOptimizationNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.post("/optimize/stream")
async def optimize_resume_stream_endpoint(
    request: ResumeOptimizeRequest,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """以 SSE 流式优化简历，逐步返回进度与结果。

    Args:
        request: 简历优化请求体（简历与优化要求）。
        user_id: 当前登录用户 ID。
    """
    try:
        event_generator = resume_optimization_use_cases.optimize_resume_stream(request=request, user_id=user_id)
    except ResumeOptimizationBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    # 以 SSE 事件流返回：禁用缓存并保持长连接
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
