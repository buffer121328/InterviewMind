"""记忆管理 API 路由。"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_current_user_id
from app.domain.memory import MemorySource
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
from ai.workflows.memory.use_cases import MemoryUseCaseError, memory_use_cases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["记忆管理"])


def _internal_error(message: str) -> HTTPException:
    """构造不包含内部堆栈和敏感数据的统一记忆服务错误响应。

    Args:
        message: 对外展示的错误消息。
    """
    return HTTPException(
        status_code=500,
        detail={"error": "InternalServerError", "message": message},
    )


@router.get("", response_model=MemoryListResponse)
async def get_all_memories(
    page_size: int = Query(100, ge=1, le=1000, description="每页数量"),
    sources: list[MemorySource] | None = Query(default=None, description="来源过滤"),
    user_id: str = Depends(get_current_user_id),
):
    """获取当前用户全部 mem0 记忆。

    Args:
        page_size: 每页数量。
        sources: 按来源过滤。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
    try:
        return await memory_use_cases.list_memories(user_id=user_id, page_size=page_size, sources=sources)
    except Exception as exc:
        logger.error("获取全部记忆失败: %s", type(exc).__name__)
        raise _internal_error("获取全部记忆失败，请检查服务端 mem0 配置") from exc


@router.post("/list", response_model=MemoryListResponse)
async def list_memories_with_model_config(
    request: MemoryListRequest,
    user_id: str = Depends(get_current_user_id),
):
    """按请求携带的模型配置列出记忆（覆盖默认 mem0 配置）。

    Args:
        request: 记忆列表请求体，可携带自定义 API 配置。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
    try:
        # 有自定义配置时透传给用例层，否则走默认配置
        api_config = request.api_config.model_dump() if request.api_config else None
        return await memory_use_cases.list_memories(
            user_id=user_id,
            page_size=request.page_size,
            sources=request.sources,
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
    sources: list[MemorySource] | None = Query(default=None, description="来源过滤"),
    user_id: str = Depends(get_current_user_id),
):
    """搜索当前用户记忆。

    Args:
        q: 搜索查询词。
        limit: 返回条数上限。
        memory_type: 按记忆类型过滤。
        sources: 按来源过滤。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
    try:
        return await memory_use_cases.search_memories(
            user_id=user_id,
            query=q,
            limit=limit,
            memory_type=memory_type,
            sources=sources,
        )
    except Exception as exc:
        logger.error("搜索记忆失败: %s", type(exc).__name__)
        raise _internal_error("搜索记忆失败，请检查服务端 mem0 配置") from exc


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories_with_model_config(
    request: MemorySearchRequest,
    user_id: str = Depends(get_current_user_id),
):
    """按请求携带的模型配置搜索记忆（覆盖默认 mem0 配置）。

    Args:
        request: 记忆搜索请求体，可携带自定义 API 配置。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
    try:
        # 有自定义配置时透传给用例层，否则走默认配置
        api_config = request.api_config.model_dump() if request.api_config else None
        return await memory_use_cases.search_memories(
            user_id=user_id,
            query=request.query,
            limit=request.limit,
            memory_type=request.memory_type,
            sources=request.sources,
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
    """整合当前用户长期记忆，需用户确认候选合并结果。

    Args:
        request: 记忆整合请求体。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
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
    """清理当前用户记忆，需用户确认清理范围。

    Args:
        request: 记忆清理请求体。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
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
    """手动新增一条当前用户记忆。

    Args:
        request: 记忆创建请求体。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
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
    """查看单条记忆的变更历史。

    Args:
        memory_id: 记忆 ID。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
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
    """按请求携带的模型配置查看记忆历史（覆盖默认 mem0 配置）。

    Args:
        memory_id: 记忆 ID。
        request: 记忆访问请求体，可携带自定义 API 配置。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
    try:
        # 有自定义配置时透传给用例层，否则走默认配置
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
    """删除当前用户的单条记忆。

    Args:
        memory_id: 记忆 ID。
        request: 可选记忆访问请求体，可携带自定义 API 配置。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
    try:
        # 有自定义配置时透传给用例层，否则走默认配置
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
    """更新当前用户的单条记忆内容。

    Args:
        memory_id: 记忆 ID。
        request: 记忆更新请求体。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
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
    """清空当前用户的全部记忆。

    Args:
        request: 清空请求体（含确认参数）。
        user_id: 当前用户 ID（用于 owner 隔离）。
    """
    try:
        return await memory_use_cases.delete_all(user_id=user_id, request=request)
    except Exception as exc:
        logger.error("清空记忆失败: %s", type(exc).__name__)
        raise _internal_error("清空记忆失败，请检查 mem0 配置") from exc
