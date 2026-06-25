"""
记忆管理 API 路由

提供用户长期记忆的查看、搜索、删除和历史查询功能。
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Query, Body

from app.services.agent_memory import get_agent_memory_service
from app.services.agent_memory.schemas import (
    MemoryItem,
    MemorySearchResponse,
    MemoryListResponse,
    MemoryHistoryItem,
    MemoryHistoryResponse,
    MemoryDeleteResponse,
    MemoryDeleteAllRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["记忆管理"])


@router.get("")
async def get_all_memories(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    page_size: int = Query(100, ge=1, le=1000, description="每页数量"),
):
    """
    获取当前用户全部 mem0 记忆
    
    Returns:
        dict: 记忆列表
    """
    try:
        user_id = x_user_id or "default_user"
        
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return {
                "success": True,
                "memories": [],
                "total": 0,
                "user_id": user_id,
                "message": "mem0 未启用",
            }
        
        memories = await memory_service.get_all(user_id=user_id, page_size=page_size)
        
        # 转换为响应格式
        memory_items = []
        for m in memories:
            memory_items.append(MemoryItem(
                id=m.get("id", ""),
                memory=m.get("memory", ""),
                metadata=m.get("metadata", {}),
                created_at=m.get("created_at"),
                updated_at=m.get("updated_at"),
            ))
        
        return {
            "success": True,
            "memories": [item.model_dump() for item in memory_items],
            "total": len(memory_items),
            "user_id": user_id,
        }
        
    except Exception as e:
        logger.error(f"获取全部记忆失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": f"获取全部记忆失败: {str(e)}",
            }
        )


@router.get("/search")
async def search_memories(
    q: str = Query(..., description="搜索查询"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    limit: int = Query(5, ge=1, le=20, description="返回数量"),
    memory_type: Optional[str] = Query(None, description="记忆类型过滤"),
):
    """
    搜索当前用户记忆
    
    Args:
        q: 搜索查询
        limit: 返回数量限制
        memory_type: 记忆类型过滤
        
    Returns:
        dict: 搜索结果
    """
    try:
        user_id = x_user_id or "default_user"
        
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return {
                "success": True,
                "memories": [],
                "query": q,
                "total": 0,
                "message": "mem0 未启用",
            }
        
        # 构造 memory_types 过滤
        memory_types = [memory_type] if memory_type else None
        
        memories = await memory_service.search_memories(
            user_id=user_id,
            query=q,
            limit=limit,
            memory_types=memory_types,
        )
        
        # 转换为响应格式
        memory_items = []
        for m in memories:
            memory_items.append(MemoryItem(
                id=m.get("id", ""),
                memory=m.get("memory", ""),
                metadata=m.get("metadata", {}),
                score=m.get("score"),
                created_at=m.get("created_at"),
                updated_at=m.get("updated_at"),
            ))
        
        return {
            "success": True,
            "memories": [item.model_dump() for item in memory_items],
            "query": q,
            "total": len(memory_items),
        }
        
    except Exception as e:
        logger.error(f"搜索记忆失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": f"搜索记忆失败: {str(e)}",
            }
        )


@router.get("/{memory_id}/history")
async def get_memory_history(
    memory_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """
    查看单条记忆变更历史
    
    Args:
        memory_id: 记忆 ID
        
    Returns:
        dict: 变更历史
    """
    try:
        user_id = x_user_id or "default_user"
        
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return {
                "success": True,
                "history": [],
                "memory_id": memory_id,
                "message": "mem0 未启用",
            }
        
        history = await memory_service.history(
            user_id=user_id,
            memory_id=memory_id,
        )
        
        # 转换为响应格式
        history_items = []
        for h in history:
            history_items.append(MemoryHistoryItem(
                id=h.get("id", ""),
                memory_id=memory_id,
                event=h.get("event", ""),
                old_memory=h.get("old_memory"),
                new_memory=h.get("new_memory"),
                created_at=h.get("created_at"),
            ))
        
        return {
            "success": True,
            "history": [item.model_dump() for item in history_items],
            "memory_id": memory_id,
        }
        
    except Exception as e:
        logger.error(f"获取记忆历史失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": f"获取记忆历史失败: {str(e)}",
            }
        )


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """
    删除当前用户某条记忆
    
    Args:
        memory_id: 记忆 ID
        
    Returns:
        dict: 删除结果
    """
    try:
        user_id = x_user_id or "default_user"
        
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return {
                "success": False,
                "message": "mem0 未启用",
            }
        
        success = await memory_service.delete(
            user_id=user_id,
            memory_id=memory_id,
        )
        
        if success:
            return {
                "success": True,
                "message": f"记忆 {memory_id} 已删除",
                "memory_id": memory_id,
            }
        else:
            return {
                "success": False,
                "message": f"删除失败，记忆 {memory_id} 不存在或不属于当前用户",
            }
        
    except Exception as e:
        logger.error(f"删除记忆失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": f"删除记忆失败: {str(e)}",
            }
        )


@router.delete("")
async def delete_all_memories(
    request: MemoryDeleteAllRequest = Body(...),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """
    清空当前用户全部记忆
    
    需要显式传入 confirm=true 才能执行删除。
    
    Args:
        request: 包含 confirm 字段的请求体
        
    Returns:
        dict: 删除结果
    """
    try:
        user_id = x_user_id or "default_user"
        
        if not request.confirm:
            return {
                "success": False,
                "message": "需要 confirm=true 才能清空全部记忆",
            }
        
        memory_service = await get_agent_memory_service()
        if not memory_service.is_enabled:
            return {
                "success": False,
                "message": "mem0 未启用",
            }
        
        success = await memory_service.delete_all(
            user_id=user_id,
            confirm=True,
        )
        
        if success:
            return {
                "success": True,
                "message": f"用户 {user_id} 的全部记忆已清空",
            }
        else:
            return {
                "success": False,
                "message": "清空记忆失败",
            }
        
    except Exception as e:
        logger.error(f"清空记忆失败: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": f"清空记忆失败: {str(e)}",
            }
        )
