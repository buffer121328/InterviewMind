"""
会话管理 API 路由
提供会话的增删改查接口
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.schemas.session import (
    SessionCreateRequest,
    SessionUpdateRequest,
    SessionListResponse,
    SessionDetailResponse,
    SessionListItem
)
from app.repositories.session.session_repo import SessionRepo
from app.api.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["会话管理"])

# 实例化会话服务
session_repo = SessionRepo()


class NextRoundRequest(BaseModel):
    """下一轮面试请求"""
    max_questions: int = Field(default=5, ge=1, le=20)


@router.post("/", response_model=SessionDetailResponse)
async def create_session(
    request: SessionCreateRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    创建新的面试会话
    
    Args:
        request: 会话创建请求
        
    Returns:
        SessionDetailResponse: 创建的会话详情
    """
    try:
        # 生成会话ID（使用UUID）
        import uuid
        session_id = str(uuid.uuid4())
        
        # 创建会话
        session = await session_repo.create_session(
            session_id=session_id,
            mode=request.mode,
            title=request.title,
            resume_filename=request.resume_filename,
            job_description=request.job_description,
            max_questions=request.max_questions,
            user_id=user_id
        )
        
        return SessionDetailResponse(
            success=True,
            session=session
        )
        
    except Exception as e:
        logger.error(f"创建会话失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "创建会话失败"
            }
        )


@router.get("/", response_model=SessionListResponse)
async def list_sessions(
    status: Optional[str] = Query(None, description="筛选状态: active, completed, archived"),
    mode: Optional[str] = Query(None, description="筛选模式: mock"),
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(0, description="偏移量"),
    user_id: str = Depends(get_current_user_id)
):
    """
    获取会话列表
    
    Args:
        status: 筛选状态
        mode: 筛选模式
        limit: 返回数量限制
        offset: 偏移量
        
    Returns:
        SessionListResponse: 会话列表
    """
    try:
        sessions = await session_repo.list_sessions(
            status=status,
            mode=mode,
            limit=limit,
            offset=offset,
            user_id=user_id
        )
        
        total = await session_repo.get_session_count(status=status, mode=mode, user_id=user_id)
        
        return SessionListResponse(
            success=True,
            sessions=sessions,
            total=total
        )
        
    except Exception as e:
        logger.error(f"获取会话列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "获取会话列表失败"
            }
        )


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    获取会话详情
    
    Args:
        session_id: 会话ID
        
    Returns:
        SessionDetailResponse: 会话详情
    """
    try:
        session = await session_repo.get_session(session_id, user_id=user_id)
        
        if session is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NotFound",
                    "message": f"会话 {session_id} 不存在"
                }
            )
        
        return SessionDetailResponse(
            success=True,
            session=session
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话详情失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "获取会话详情失败"
            }
        )


@router.patch("/{session_id}", response_model=SessionDetailResponse)
async def update_session(
    session_id: str, 
    request: SessionUpdateRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    更新会话信息
    
    Args:
        session_id: 会话ID
        request: 更新请求
        
    Returns:
        SessionDetailResponse: 更新后的会话详情
    """
    try:
        session = await session_repo.update_session(
            session_id=session_id,
            title=request.title,
            status=request.status,
            metadata_updates=request.metadata,
            user_id=user_id
        )
        
        if session is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NotFound",
                    "message": f"会话 {session_id} 不存在"
                }
            )
        
        return SessionDetailResponse(
            success=True,
            session=session
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新会话失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "更新会话失败"
            }
        )


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    删除会话
    """
    try:
        # 1. 先检查是否存在
        session = await session_repo.get_session(session_id, user_id=user_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NotFound",
                    "message": f"会话 {session_id} 不存在或无权访问"
                }
            )
            
        # 2. 执行删除
        success = await session_repo.delete_session(session_id, user_id=user_id)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "InternalServerError",
                    "message": f"无法删除会话 {session_id}，请检查后台日志"
                }
            )
        
        return {
            "success": True,
            "message": f"会话 {session_id} 已删除"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": f"删除会话过程出现异常: {str(e)}"
            }
        )


@router.post("/{session_id}/messages")
async def add_message_to_session(
    session_id: str,
    role: str,
    content: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    向会话添加消息
    
    Args:
        session_id: 会话ID
        role: 消息角色
        content: 消息内容
        
    Returns:
        dict: 添加结果
    """
    try:
        session = await session_repo.add_message(
            session_id=session_id,
            role=role,
            content=content,
            user_id=user_id
        )
        
        if session is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NotFound",
                    "message": f"会话 {session_id} 不存在"
                }
            )
        
        return {
            "success": True,
            "message": "消息已添加",
            "message_count": len(session.messages)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加消息失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "添加消息失败"
            }
        )


@router.post("/{session_id}/next-round", response_model=SessionDetailResponse)
async def create_next_round(
    session_id: str,
    request: NextRoundRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    从已完成的面试创建下一轮面试
    
    Args:
        session_id: 上一轮会话ID
        request: 下一轮请求
        
    Returns:
        SessionDetailResponse: 新会话详情
    """
    try:
        new_session = await session_repo.create_next_round(
            parent_session_id=session_id,
            max_questions=request.max_questions,
            user_id=user_id
        )
        
        return SessionDetailResponse(
            success=True,
            session=new_session
        )
        
    except ValueError as e:
        # 业务逻辑错误（如未完成的面试）
        raise HTTPException(
            status_code=400,
            detail={
                "error": "BadRequest",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"创建下一轮面试失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "InternalServerError",
                "message": "创建下一轮面试失败"
            }
        )
