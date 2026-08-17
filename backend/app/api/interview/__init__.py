"""面试相关 API 路由。

对应 ai/workflows/interview/，聚合聊天、会话管理、语音面试三类路由。
"""

from fastapi import APIRouter

from . import chat, sessions, voice

router = APIRouter()
router.include_router(chat.router)
router.include_router(sessions.router)
router.include_router(voice.router)

__all__ = ["router", "chat", "sessions", "voice"]
