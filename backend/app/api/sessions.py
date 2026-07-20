"""
会话管理 API 路由
提供会话的增删改查接口
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user_id
from app.workflows.interview.sessions import (
    SessionManagementNotFound,
    SessionManagementPersistenceError,
    session_management_use_cases,
)
from app.schemas.session import (
    SessionCreateRequest,
    SessionUpdateRequest,
    SessionListResponse,
    SessionDetailResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["会话管理"])


class NextRoundRequest(BaseModel):
    """下一轮面试请求"""

    max_questions: int = Field(default=5, ge=1, le=20)


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": "NotFound", "message": message},
    )


def _internal_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=500,
        detail={"error": "InternalServerError", "message": message},
    )


@router.post("/", response_model=SessionDetailResponse)
async def create_session(
    request: SessionCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建新的面试会话。"""
    try:
        session = await session_management_use_cases.create_session(request=request, user_id=user_id)
        return SessionDetailResponse(success=True, session=session)
    except Exception as exc:
        logger.error("创建会话失败: %s", exc)
        raise _internal_error("创建会话失败") from exc


@router.get("/", response_model=SessionListResponse)
async def list_sessions(
    status: Optional[str] = Query(None, description="筛选状态: active, completed, archived"),
    mode: Optional[str] = Query(None, description="筛选模式: mock"),
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(0, description="偏移量"),
    user_id: str = Depends(get_current_user_id),
):
    """获取会话列表。"""
    try:
        sessions, total = await session_management_use_cases.list_sessions(
            status=status,
            mode=mode,
            limit=limit,
            offset=offset,
            user_id=user_id,
        )
        return SessionListResponse(success=True, sessions=sessions, total=total)
    except Exception as exc:
        logger.error("获取会话列表失败: %s", exc)
        raise _internal_error("获取会话列表失败") from exc


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """获取会话详情。"""
    try:
        session = await session_management_use_cases.get_session(session_id=session_id, user_id=user_id)
        return SessionDetailResponse(success=True, session=session)
    except SessionManagementNotFound as exc:
        raise _not_found(exc.message) from exc
    except Exception as exc:
        logger.error("获取会话详情失败: %s", exc)
        raise _internal_error("获取会话详情失败") from exc


@router.patch("/{session_id}", response_model=SessionDetailResponse)
async def update_session(
    session_id: str,
    request: SessionUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """更新会话信息。"""
    try:
        session = await session_management_use_cases.update_session(
            session_id=session_id,
            request=request,
            user_id=user_id,
        )
        return SessionDetailResponse(success=True, session=session)
    except SessionManagementNotFound as exc:
        raise _not_found(exc.message) from exc
    except Exception as exc:
        logger.error("更新会话失败: %s", exc)
        raise _internal_error("更新会话失败") from exc


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """删除会话。"""
    try:
        await session_management_use_cases.delete_session(session_id=session_id, user_id=user_id)
        return {"success": True, "message": f"会话 {session_id} 已删除"}
    except SessionManagementNotFound as exc:
        raise _not_found(exc.message) from exc
    except SessionManagementPersistenceError as exc:
        raise _internal_error(exc.message) from exc
    except Exception as exc:
        logger.error("删除会话失败: %s", exc)
        raise _internal_error(f"删除会话过程出现异常: {exc}") from exc


@router.post("/{session_id}/messages")
async def add_message_to_session(
    session_id: str,
    role: str,
    content: str,
    user_id: str = Depends(get_current_user_id),
):
    """向会话添加消息。"""
    try:
        session = await session_management_use_cases.add_message(
            session_id=session_id,
            role=role,
            content=content,
            user_id=user_id,
        )
        return {"success": True, "message": "消息已添加", "message_count": len(session.messages)}
    except SessionManagementNotFound as exc:
        raise _not_found(exc.message) from exc
    except Exception as exc:
        logger.error("添加消息失败: %s", exc)
        raise _internal_error("添加消息失败") from exc


@router.post("/{session_id}/next-round", response_model=SessionDetailResponse)
async def create_next_round(
    session_id: str,
    request: NextRoundRequest,
    user_id: str = Depends(get_current_user_id),
):
    """从已完成的面试创建下一轮面试。"""
    try:
        new_session = await session_management_use_cases.create_next_round(
            session_id=session_id,
            max_questions=request.max_questions,
            user_id=user_id,
        )
        return SessionDetailResponse(success=True, session=new_session)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "BadRequest", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.error("创建下一轮面试失败: %s", exc)
        raise _internal_error("创建下一轮面试失败") from exc
