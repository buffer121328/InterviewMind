"""记忆管理 API 路由。"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_current_user_id
from app.schemas.memory import (
    MemoryDeleteAllRequest,
    MemoryDeleteResponse,
    MemoryHistoryResponse,
    MemoryListResponse,
    MemorySearchResponse,
)
from app.workflows.memory import memory_use_cases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["记忆管理"])


def _internal_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=500,
        detail={"error": "InternalServerError", "message": message},
    )


@router.get("", response_model=MemoryListResponse)
async def get_all_memories(
    page_size: int = Query(100, ge=1, le=1000, description="每页数量"),
    user_id: str = Depends(get_current_user_id),
):
    """获取当前用户全部 mem0 记忆。"""
    try:
        return await memory_use_cases.list_memories(user_id=user_id, page_size=page_size)
    except Exception as exc:
        logger.error("获取全部记忆失败: %s", exc)
        raise _internal_error(f"获取全部记忆失败: {exc}") from exc


@router.get("/search", response_model=MemorySearchResponse)
async def search_memories(
    q: str = Query(..., description="搜索查询"),
    limit: int = Query(5, ge=1, le=20, description="返回数量"),
    memory_type: str | None = Query(None, description="记忆类型过滤"),
    user_id: str = Depends(get_current_user_id),
):
    """搜索当前用户记忆。"""
    try:
        return await memory_use_cases.search_memories(
            user_id=user_id,
            query=q,
            limit=limit,
            memory_type=memory_type,
        )
    except Exception as exc:
        logger.error("搜索记忆失败: %s", exc)
        raise _internal_error(f"搜索记忆失败: {exc}") from exc


@router.get("/{memory_id}/history", response_model=MemoryHistoryResponse)
async def get_memory_history(
    memory_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """查看单条记忆变更历史。"""
    try:
        return await memory_use_cases.get_history(user_id=user_id, memory_id=memory_id)
    except Exception as exc:
        logger.error("获取记忆历史失败: %s", exc)
        raise _internal_error(f"获取记忆历史失败: {exc}") from exc


@router.delete("/{memory_id}", response_model=MemoryDeleteResponse)
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """删除当前用户某条记忆。"""
    try:
        return await memory_use_cases.delete_memory(user_id=user_id, memory_id=memory_id)
    except Exception as exc:
        logger.error("删除记忆失败: %s", exc)
        raise _internal_error(f"删除记忆失败: {exc}") from exc


@router.delete("", response_model=MemoryDeleteResponse)
async def delete_all_memories(
    request: MemoryDeleteAllRequest = Body(...),
    user_id: str = Depends(get_current_user_id),
):
    """清空当前用户全部记忆。"""
    try:
        return await memory_use_cases.delete_all(user_id=user_id, request=request)
    except Exception as exc:
        logger.error("清空记忆失败: %s", exc)
        raise _internal_error(f"清空记忆失败: {exc}") from exc
