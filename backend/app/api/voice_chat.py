"""
语音面试 API 路由
只负责请求/响应处理，业务逻辑在 services/voice_interview.py
"""

import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.schemas.voice import (
    VoiceStartRequest,
    VoiceChatRequest,
    VoiceStartResponse,
    VoiceCloneRequest,
)

from app.agents.interview.voice_interview import generate_voice_summary
from app.api.deps import get_current_user_id
from app.workflows.interview.voice import VoiceInterviewUseCaseError, voice_interview_use_cases
from app.workflows.interview.voice_stream import VoiceStreamUseCaseError, voice_stream_use_cases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["语音面试"])




# ============================================================================
# 接口实现
# ============================================================================

@router.post("/start", response_model=VoiceStartResponse)
async def start_voice_interview(
    request: VoiceStartRequest,
    user_id: str = Depends(get_current_user_id),
):
    """开始语音面试。"""
    try:
        return await voice_interview_use_cases.start(request=request, user_id=user_id)
    except VoiceInterviewUseCaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[Voice] 启动面试失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat")
async def voice_chat_endpoint(
    request: VoiceChatRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    语音对话接口 (SSE 流式输出)
    """
    try:
        generator = await voice_stream_use_cases.stream_voice_chat(request=request, user_id=user_id)
    except VoiceStreamUseCaseError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Nginx 禁用缓冲
        }
    )



@router.post("/clone")
async def clone_voice_session(
    request: VoiceCloneRequest,
    user_id: str = Depends(get_current_user_id),
):
    """克隆当前会话用于语音面试。"""
    try:
        return await voice_interview_use_cases.clone(request=request, user_id=user_id)
    except Exception as exc:
        logger.error("[Voice] 克隆会话失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class VoiceSummaryRequest(BaseModel):
    session_id: str
    api_config: dict[str, Any]


@router.post("/summary")
async def voice_summary_endpoint(
    request: VoiceSummaryRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    生成语音面试总结（SSE 流式输出）
    
    在面试完成后调用此接口生成面试反馈总结。
    """
    generator = generate_voice_summary(
        session_id=request.session_id,
        api_config=request.api_config,
        user_id=user_id
    )
    
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
