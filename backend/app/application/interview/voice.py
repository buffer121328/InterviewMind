"""语音面试应用层用例。"""

from __future__ import annotations

import logging
from typing import Any

from app.repositories.session.session_repo import SessionRepo
from app.schemas.voice import VoiceCloneRequest, VoiceStartRequest, VoiceStartResponse
from app.services.interview.interview_context import build_interview_context
from app.services.interview.voice_interview import (
    build_system_prompt,
    generate_interview_plan,
    get_opening_message,
)

logger = logging.getLogger(__name__)


class VoiceInterviewUseCaseError(Exception):
    """语音面试应用层错误。"""

    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class VoiceInterviewUseCases:
    """语音面试非流式应用层门面。"""

    def __init__(self) -> None:
        self._session_repo = SessionRepo()

    async def start(self, *, request: VoiceStartRequest, user_id: str) -> VoiceStartResponse:
        session_id = request.thread_id
        api_config: dict[str, Any] = request.api_config

        logger.info("[Voice] 开始语音面试: %s", session_id)

        session = await self._session_repo.get_session(
            session_id,
            include_resume_content=True,
            user_id=user_id,
        )
        if not session and await self._session_repo.get_session(session_id) is not None:
            raise VoiceInterviewUseCaseError("会话不存在或无权访问", status_code=404)

        is_switching_from_text = bool(session and session.metadata.mode == "mock")

        if is_switching_from_text:
            logger.info("[Voice] 检测到文字面试切换: %s，执行复用逻辑...", session_id)
            session = await self._session_repo.clone_session_for_voice(
                session_id,
                user_id=user_id,
                max_questions=request.max_questions,
            )
            session_id = session.session_id
            logger.info("[Voice] 已复用并生成新对话: %s", session_id)

        if not session:
            logger.info("[Voice] 会话 %s 不存在，正在创建新会话...", session_id)
            await self._session_repo.create_session(
                session_id=session_id,
                mode="voice",
                resume_filename=request.resume_filename,
                resume_content=request.resume_content,
                job_description=request.job_description,
                company_info=request.company_info or "未知",
                max_questions=request.max_questions,
                user_id=user_id,
            )
            session = await self._session_repo.get_session(session_id, include_resume_content=True)
            if not session:
                raise VoiceInterviewUseCaseError("创建会话失败", status_code=500)

        history_messages = [
            {
                "role": msg.role,
                "content": msg.content,
                "audio_url": msg.audio_url,
            }
            for msg in (session.messages or [])
            if msg.role != "system" and msg.content
        ]

        interview_plan = await self._session_repo.get_interview_plan(session_id)
        if not interview_plan:
            logger.info("[Voice] 会话 %s 计划为空，正在生成...", session_id)
            context = await build_interview_context(
                user_id=user_id,
                resume_context=None,
                job_description=None,
                company_info=None,
                max_questions=None,
                question_bank_count=request.question_bank_count,
                experience_questions=request.experience_questions,
                session_metadata=session.metadata,
            )
            interview_plan = await generate_interview_plan(
                resume=context.resume_context,
                job_description=context.job_description,
                company_info=context.company_info,
                max_questions=context.max_questions,
                api_config=api_config,
                session_id=session_id,
                user_id=user_id,
                question_bank_count=context.question_bank_count,
                experience_questions=list(context.experience_questions),
                memory_context=context.memory_context,
            )
            await self._session_repo.save_interview_plan(session_id, interview_plan)
        else:
            logger.info("[Voice] 已有面试计划, 共 %s 道题", len(interview_plan))

        round_index = getattr(session.metadata, "round_index", 1) or 1
        first_question_content = None
        if interview_plan:
            current_q_idx = getattr(session.metadata, "question_count", 0)
            if current_q_idx < len(interview_plan):
                first_question_content = interview_plan[current_q_idx].get("content")

        if is_switching_from_text:
            opening_msg_text = "好的，那我们切换到语音模式继续。关于刚才的话题，或者我们换个方向，我想请问一下：" + (
                first_question_content or "准备好了吗？"
            )
        else:
            opening_msg_text = get_opening_message(first_question_content, round_index)

        last_message = session.messages[-1] if session.messages else None
        has_history = len(history_messages) > 0

        if not is_switching_from_text:
            opening_keywords = ["我是你的面试官", "我是本轮的面试官", "我将继续担任你的面试官"]
            is_opening_message = (
                last_message
                and last_message.role == "assistant"
                and any(keyword in last_message.content for keyword in opening_keywords)
            )

            if is_opening_message or has_history:
                logger.info("[Voice] 会话 %s 已有历史，执行静默恢复", session_id)
                return VoiceStartResponse(
                    success=True,
                    session_id=session_id,
                    system_prompt=build_system_prompt(interview_plan),
                    first_question=last_message.content if last_message else "",
                    audio=None,
                    greeting_text=None,
                    history=history_messages,
                    round_index=round_index,
                    question_count=getattr(session.metadata, "question_count", 0),
                    max_questions=session.metadata.max_questions or 5,
                )

        return VoiceStartResponse(
            success=True,
            session_id=session_id,
            system_prompt=build_system_prompt(interview_plan),
            first_question=opening_msg_text,
            audio=None,
            greeting_text=opening_msg_text,
            history=history_messages,
            round_index=round_index,
            question_count=getattr(session.metadata, "question_count", 0),
            max_questions=session.metadata.max_questions or 5,
        )

    async def clone(self, *, request: VoiceCloneRequest, user_id: str) -> dict[str, object]:
        new_session = await self._session_repo.clone_session_for_voice(
            request.source_session_id,
            user_id=user_id,
            max_questions=request.max_questions,
        )
        return {"success": True, "new_session_id": new_session.session_id}


voice_interview_use_cases = VoiceInterviewUseCases()
