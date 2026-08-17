"""提供简历历史相关后端功能。"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user_id
from app.schemas.resume.resume_schemas import (
    CompletedSessionsResponse,
    ResumeHistoryDetailResponse,
    ResumeHistoryListResponse,
)
from ai.workflows.resume.history import ResumeHistoryNotFound, resume_history_use_cases

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/sessions", response_model=CompletedSessionsResponse)
async def get_completed_sessions(
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
    limit: int = 10,
):
    """获取当前用户已完成的简历会话列表。

    Args:
        user_id: 当前登录用户 ID。
        limit: 返回条数上限，默认 10。
    """
    logger.info("获取已完成会话: user_id=%s", user_id)
    return await resume_history_use_cases.get_completed_sessions(user_id=user_id, limit=limit)


@router.get("/results", response_model=ResumeHistoryListResponse)
async def list_resume_results(
    result_type: Optional[Literal["analyze", "optimize"]] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_data: bool = Query(default=True, description="是否在列表中返回完整简历和结果 JSON"),
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """分页列出当前用户的简历分析/优化结果。

    Args:
        result_type: 结果类型过滤（analyze=分析 / optimize=优化），为空则全部。
        limit: 分页大小，范围 1~100，默认 20。
        offset: 分页偏移量，默认 0。
        include_data: 是否在列表内联返回完整简历与结果数据。
        user_id: 当前登录用户 ID。
    """
    return await resume_history_use_cases.list_resume_results(
        user_id=user_id,
        result_type=result_type,
        limit=limit,
        offset=offset,
        include_data=include_data,
    )


@router.get("/results/{result_id}", response_model=ResumeHistoryDetailResponse)
async def get_resume_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """获取单条简历结果的详情。

    Args:
        result_id: 简历结果 ID。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_history_use_cases.get_resume_result(result_id=result_id, user_id=user_id)
    except ResumeHistoryNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/results/{result_id}")
async def delete_resume_result(
    result_id: int,
    user_id: str = Depends(get_current_user_id),  # 鉴权：注入当前登录用户 ID
):
    """删除一条简历结果。

    Args:
        result_id: 简历结果 ID。
        user_id: 当前登录用户 ID。
    """
    try:
        return await resume_history_use_cases.delete_resume_result(result_id=result_id, user_id=user_id)
    except ResumeHistoryNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("删除结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
