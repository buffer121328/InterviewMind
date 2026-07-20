"""
聊天相关的 API 路由
支持 Server-Sent Events (SSE) 流式输出
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Body, Depends
from fastapi.responses import StreamingResponse

from app.schemas.schemas import ChatRequest, ChatStreamResponse, InterviewStartRequest, ErrorResponse, RollbackRequest, ProfileGenerateRequest, WeaknessGenerateRequest
from app.api.deps import get_current_user_id
from app.workflows.interview.session_actions import InterviewSessionNotFound, interview_session_use_cases
from app.workflows.interview.stream import (
    ChatStreamBadRequest,
    ChatStreamConflict,
    ChatStreamNotFound,
    chat_stream_use_cases,
)
from app.workflows.interview.start import (
    InterviewStartFailed,
    InterviewStartNotFound,
    interview_start_use_cases,
)
from app.workflows.interview.reports import (
    InterviewReportBadRequest,
    InterviewReportNotFound,
    interview_report_use_cases,
)

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["聊天"])

@router.get("/hint/{session_id}/{question_index}")
async def get_hint(
    session_id: str,
    question_index: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取指定问题的回答提示。"""
    try:
        return await interview_session_use_cases.get_hint(
            session_id=session_id,
            question_index=question_index,
            user_id=user_id,
        )
    except InterviewSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取回答提示失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取回答提示失败"},
        ) from exc

@router.post("/start")
async def start_interview(
    request: InterviewStartRequest,
    user_id: str = Depends(get_current_user_id)):
    """开始新的面试会话。"""
    try:
        return await interview_start_use_cases.start_interview(request=request, user_id=user_id)
    except InterviewStartNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except InterviewStartFailed as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": exc.error, "message": exc.message},
        ) from exc

@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    user_id: str = Depends(get_current_user_id)
):
    """SSE 端点：流式聊天接口。"""
    try:
        event_generator = await chat_stream_use_cases.stream_chat(request=request, user_id=user_id)
    except ChatStreamBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ChatStreamNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ChatStreamConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=exc.message,
            headers={"Retry-After": exc.retry_after},
        ) from exc
    except Exception as exc:
        logger.error("流式聊天初始化失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "流式聊天初始化失败"},
        ) from exc
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )

@router.get("/status/{thread_id}")
async def get_chat_status(thread_id: str):
    """获取聊天会话状态。"""
    try:
        return await interview_session_use_cases.get_chat_status(thread_id=thread_id)
    except Exception as exc:
        logger.error("获取聊天状态失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取聊天状态失败"},
        ) from exc


@router.delete("/session/{thread_id}")
async def end_chat_session(thread_id: str):
    """结束聊天会话。"""
    try:
        return await interview_session_use_cases.end_chat_session(thread_id=thread_id)
    except Exception as exc:
        logger.error("结束聊天会话失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "结束聊天会话失败"},
        ) from exc


@router.post("/rollback")
async def rollback_chat(
    request: RollbackRequest,
    user_id: str = Depends(get_current_user_id)):
    """回退聊天会话。"""
    try:
        return await interview_session_use_cases.rollback_chat(request=request, user_id=user_id)
    except InterviewSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("回退会话失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "回退会话失败"},
        ) from exc

@router.post("/profile/generate")
async def generate_profile(
    request: Optional[ProfileGenerateRequest] = Body(None),
    user_id: str = Depends(get_current_user_id)):
    """手动触发：生成用户综合能力画像。"""
    try:
        return await interview_report_use_cases.generate_profile(request=request, user_id=user_id)
    except Exception as exc:
        logger.error("生成综合能力画像失败: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": f"生成综合能力画像失败: {exc}"},
        ) from exc


@router.get("/profile/overall")
async def get_overall_profile(
    user_id: str = Depends(get_current_user_id)):
    """获取用户综合能力画像（从数据库读取已生成的画像）。"""
    try:
        return await interview_report_use_cases.get_overall_profile(user_id=user_id)
    except Exception as exc:
        logger.error("获取综合能力画像失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取综合能力画像失败"},
        ) from exc


@router.get("/profile/session/{session_id}")
async def get_session_profile(
    session_id: str,
    user_id: str = Depends(get_current_user_id)):
    """获取单个会话的能力画像。"""
    try:
        return await interview_report_use_cases.get_session_profile(session_id=session_id, user_id=user_id)
    except InterviewReportNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取会话画像失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取会话画像失败"},
        ) from exc


# ============================================================================
# 短板地图接口
# ============================================================================

@router.post("/weakness/generate")
async def generate_weakness_report(
    request: WeaknessGenerateRequest = Body(...),
    user_id: str = Depends(get_current_user_id)):
    """为指定会话生成短板地图报告。"""
    try:
        return await interview_report_use_cases.generate_weakness_report(request=request, user_id=user_id)
    except InterviewReportBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except InterviewReportNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("生成短板地图失败: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": f"生成短板地图失败: {exc}"},
        ) from exc


@router.get("/weakness/session/{session_id}")
async def get_weakness_by_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id)):
    """获取指定会话的短板地图报告。"""
    try:
        return await interview_report_use_cases.get_weakness_by_session(session_id=session_id, user_id=user_id)
    except Exception as exc:
        logger.error("获取短板地图失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取短板地图失败"},
        ) from exc


@router.get("/weakness/history")
async def get_weakness_history(
    user_id: str = Depends(get_current_user_id)):
    """获取用户的短板地图历史列表。"""
    try:
        return await interview_report_use_cases.get_weakness_history(user_id=user_id)
    except Exception as exc:
        logger.error("获取短板地图历史失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取短板地图历史失败"},
        ) from exc
