"""
聊天相关的 API 路由
支持 Server-Sent Events (SSE) 流式输出
"""

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ai.workflows.interview.chat.stream import (
    ChatStreamBadRequest,
    ChatStreamConflict,
    ChatStreamNotFound,
    chat_stream_use_cases,
)
from ai.workflows.interview.lifecycle.start import (
    InterviewStartFailed,
    InterviewStartNotFound,
    interview_start_use_cases,
)
from ai.workflows.interview.reports.use_cases import (
    InterviewReportBadRequest,
    InterviewReportNotFound,
    interview_report_use_cases,
)
from ai.workflows.interview.sessions.actions import (
    InterviewSessionNotFound,
    interview_session_use_cases,
)
from app.api.deps import get_current_user_id
from app.schemas.interview.interview_report import (
    SaveReportQuestionsRequest,
    SaveReportQuestionsResponse,
)
from app.schemas.interview.schemas import (
    ChatRequest,
    InterviewStartRequest,
    ProfileGenerateRequest,
    RollbackRequest,
)
from app.schemas.interview.session import SessionMarkdownReportResponse

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["聊天"])

@router.get("/hint/{session_id}/{question_index}")
async def get_hint(
    session_id: str,
    question_index: int,
    user_id: str = Depends(get_current_user_id)
):
    """获取指定问题的回答提示。

    Args:
        session_id: 面试会话 ID。
        question_index: 题目序号（从 0 开始）。
        user_id: 当前登录用户 ID（由鉴权依赖注入）。
    """
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
    """开始新的面试会话。

    Args:
        request: 面试启动请求（含简历、岗位与目标等信息）。
        user_id: 当前登录用户 ID（由鉴权依赖注入）。
    """
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
    """SSE 端点：发送面试消息并流式返回模型回复。

    Args:
        request: 聊天请求（含会话 ID 与用户消息）。
        user_id: 当前登录用户 ID（由鉴权依赖注入）。
    """
    try:
        # ① 初始化事件生成器（异步生成 SSE 事件序列）
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
        from app.security.security import safe_error_message

        logger.error("流式聊天初始化失败: %s", safe_error_message(exc))
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
        },
    )

@router.post("/rollback")
async def rollback_chat(
    request: RollbackRequest,
    user_id: str = Depends(get_current_user_id)):
    """回退聊天会话（撤销最近一次交互）。

    Args:
        request: 回退请求（含会话 ID 与回退步数）。
        user_id: 当前登录用户 ID（由鉴权依赖注入）。
    """
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
    """手动触发：生成用户综合能力画像。

    Args:
        request: 画像生成请求（可选，携带则指定生成范围）。
        user_id: 当前登录用户 ID（由鉴权依赖注入）。
    """
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
    """获取用户综合能力画像（从数据库读取已生成的画像）。

    Args:
        user_id: 当前登录用户 ID（由鉴权依赖注入）。
    """
    try:
        return await interview_report_use_cases.get_overall_profile(user_id=user_id)
    except Exception as exc:
        logger.error("获取综合能力画像失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取综合能力画像失败"},
        ) from exc


@router.get("/report/session/{session_id}", response_model=SessionMarkdownReportResponse)
async def get_session_report(
    session_id: str,
    user_id: str = Depends(get_current_user_id)):
    """获取单场面试的统一 Markdown 报告。

    Args:
        session_id: 面试会话 ID。
        user_id: 当前登录用户 ID（由鉴权依赖注入）。
    """
    try:
        return await interview_report_use_cases.get_session_report(
            session_id=session_id,
            user_id=user_id,
        )
    except InterviewReportNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:
        logger.error("获取面试报告失败: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "InternalServerError", "message": "获取面试报告失败"},
        ) from exc


@router.post("/report/session/{session_id}/questions", response_model=SaveReportQuestionsResponse)
async def save_session_report_questions(
    session_id: str,
    request: SaveReportQuestionsRequest,
    user_id: str = Depends(get_current_user_id),
):
    """把 owner 可见报告中的选中推荐题幂等保存到题库。

    Args:
        session_id: 面试会话 ID。
        request: 待保存的推荐题列表请求。
        user_id: 当前登录用户 ID（由鉴权依赖注入）。
    """
    try:
        return await interview_report_use_cases.save_recommended_questions(
            session_id=session_id, request=request, user_id=user_id
        )
    except InterviewReportNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except InterviewReportBadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
