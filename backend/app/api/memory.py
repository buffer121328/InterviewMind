"""记忆管理 API 路由。"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_current_user_id
from app.schemas.memory import (
    MemoryAccessRequest,
    MemoryCleanupRequest,
    MemoryCleanupResponse,
    MemoryCreateRequest,
    MemoryConsolidateRequest,
    MemoryConsolidationResponse,
    MemoryDeleteAllRequest,
    MemoryDeleteResponse,
    MemoryHistoryResponse,
    MemoryListRequest,
    MemoryListResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryUpdateRequest,
    MemoryWriteResponse,
)
from ai.workflows.memory import MemoryUseCaseError, memory_use_cases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["记忆管理"])


def _internal_error(message: str) -> HTTPException:
    """构造不包含内部堆栈和敏感数据的统一记忆服务错误响应。"""
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
        logger.error("获取全部记忆失败: %s", type(exc).__name__)
        raise _internal_error("获取全部记忆失败，请检查服务端 mem0 配置") from exc


@router.post("/list", response_model=MemoryListResponse)
async def list_memories_with_model_config(
    request: MemoryListRequest,
    user_id: str = Depends(get_current_user_id),
):
    """List memories using front-end model channels without persisting credentials."""
    try:
        api_config = request.api_config.model_dump() if request.api_config else None
        return await memory_use_cases.list_memories(
            user_id=user_id,
            page_size=request.page_size,
            api_config=api_config,
        )
    except Exception as exc:
        logger.error("获取全部记忆失败: %s", type(exc).__name__)
        raise _internal_error("获取全部记忆失败，请检查 mem0 模型与向量库配置") from exc


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
        logger.error("搜索记忆失败: %s", type(exc).__name__)
        raise _internal_error("搜索记忆失败，请检查服务端 mem0 配置") from exc


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories_with_model_config(
    request: MemorySearchRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Search memories using front-end model channels without placing credentials in the URL."""
    try:
        api_config = request.api_config.model_dump() if request.api_config else None
        return await memory_use_cases.search_memories(
            user_id=user_id,
            query=request.query,
            limit=request.limit,
            memory_type=request.memory_type,
            api_config=api_config,
        )
    except Exception as exc:
        logger.error("搜索记忆失败: %s", type(exc).__name__)
        raise _internal_error("搜索记忆失败，请检查 mem0 模型与向量库配置") from exc


@router.post("/consolidate", response_model=MemoryConsolidationResponse)
async def consolidate_memories(
    request: MemoryConsolidateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Preview or explicitly apply owner-scoped historical memory consolidation."""
    try:
        return await memory_use_cases.consolidate_memories(
            user_id=user_id,
            request=request,
        )
    except MemoryUseCaseError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "MemoryConfirmationRequired", "message": exc.message},
        ) from exc
    except Exception as exc:
        logger.error("整合长期记忆失败: %s", type(exc).__name__)
        raise _internal_error("整合长期记忆失败，请检查 mem0 模型与向量库配置") from exc


@router.post("/cleanup", response_model=MemoryCleanupResponse)
async def cleanup_memories(
    request: MemoryCleanupRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Preview or apply two-stage owner-scoped retention cleanup."""

    try:
        return await memory_use_cases.cleanup_memories(user_id=user_id, request=request)
    except MemoryUseCaseError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "MemoryCleanupConfirmationRequired", "message": exc.message},
        ) from exc
    except Exception as exc:
        logger.error("清理长期记忆失败: %s", type(exc).__name__)
        raise _internal_error("清理长期记忆失败，请检查 mem0 与 Redis 配置") from exc


@router.post("", response_model=MemoryWriteResponse)
async def add_memory(
    request: MemoryCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Add one user-authored memory without automatic LLM extraction."""
    try:
        return await memory_use_cases.add_memory(user_id=user_id, request=request)
    except Exception as exc:
        logger.error("手动添加记忆失败: %s", type(exc).__name__)
        raise _internal_error("添加记忆失败，请检查 mem0 配置") from exc


@router.get("/{memory_id}/history", response_model=MemoryHistoryResponse)
async def get_memory_history(
    memory_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """查看单条记忆变更历史。"""
    try:
        return await memory_use_cases.get_history(user_id=user_id, memory_id=memory_id)
    except Exception as exc:
        logger.error("获取记忆历史失败: %s", type(exc).__name__)
        raise _internal_error("获取记忆历史失败，请检查服务端 mem0 配置") from exc


@router.post("/{memory_id}/history", response_model=MemoryHistoryResponse)
async def get_memory_history_with_model_config(
    memory_id: str,
    request: MemoryAccessRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Read one memory history through request-scoped model channels."""
    try:
        api_config = request.api_config.model_dump() if request.api_config else None
        return await memory_use_cases.get_history(
            user_id=user_id,
            memory_id=memory_id,
            api_config=api_config,
        )
    except Exception as exc:
        logger.error("获取记忆历史失败: %s", type(exc).__name__)
        raise _internal_error("获取记忆历史失败，请检查 mem0 配置") from exc


@router.delete("/{memory_id}", response_model=MemoryDeleteResponse)
async def delete_memory(
    memory_id: str,
    request: MemoryAccessRequest | None = Body(default=None),
    user_id: str = Depends(get_current_user_id),
):
    """Delete one memory using request-scoped model channels when supplied."""
    try:
        api_config = request.api_config.model_dump() if request and request.api_config else None
        return await memory_use_cases.delete_memory(
            user_id=user_id,
            memory_id=memory_id,
            api_config=api_config,
        )
    except Exception as exc:
        logger.error("删除记忆失败: %s", type(exc).__name__)
        raise _internal_error("删除记忆失败，请检查 mem0 配置") from exc


@router.patch("/{memory_id}", response_model=MemoryWriteResponse)
async def update_memory(
    memory_id: str,
    request: MemoryUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Update one owner-scoped memory after validating its ownership."""
    try:
        return await memory_use_cases.update_memory(
            user_id=user_id,
            memory_id=memory_id,
            request=request,
        )
    except Exception as exc:
        logger.error("更新记忆失败: %s", type(exc).__name__)
        raise _internal_error("更新记忆失败，请检查 mem0 配置") from exc


@router.delete("", response_model=MemoryDeleteResponse)
async def delete_all_memories(
    request: MemoryDeleteAllRequest = Body(...),
    user_id: str = Depends(get_current_user_id),
):
    """Clear all owner-scoped memories through the request-scoped mem0 client."""
    try:
        return await memory_use_cases.delete_all(user_id=user_id, request=request)
    except Exception as exc:
        logger.error("清空记忆失败: %s", type(exc).__name__)
        raise _internal_error("清空记忆失败，请检查 mem0 配置") from exc
