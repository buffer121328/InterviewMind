"""语音面试流式回复用例。"""

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.schemas.voice import VoiceChatRequest
from app.services.agent_runs.service import AgentRunService, TASK_TYPE_VOICE_INTERVIEW_TURN
from app.services.interview.voice_interview import process_voice_chat
from app.services.security import safe_error_message


@dataclass(slots=True)
class VoiceStreamUseCaseError(Exception):
    """语音面试流式用例异常。"""

    message: str


class VoiceStreamUseCases:
    """语音面试流式应用服务。"""

    def __init__(self) -> None:
        self._run_service = AgentRunService()

    async def stream_voice_chat(self, *, request: VoiceChatRequest, user_id: str) -> AsyncGenerator[str, None]:
        run, _ = await self._run_service.create_or_get(
            user_id=user_id,
            task_type=TASK_TYPE_VOICE_INTERVIEW_TURN,
            idempotency_key=f"voice-turn:{request.session_id}:{request.audio_id or 'text'}:{id(request)}",
            payload={
                "session_id": request.session_id,
                "has_audio": bool(request.audio),
                "has_text": bool(request.message),
                "is_greeting": bool(request.is_greeting),
            },
        )
        claimed = await self._run_service.claim(run.id)
        if claimed is None:
            raise VoiceStreamUseCaseError(message="语音面试任务状态异常，请稍后重试")
        await self._run_service.mark_stage(run.id, "generating_response")
        source = process_voice_chat(
            session_id=request.session_id,
            system_prompt=request.system_prompt,
            history=request.history,
            audio_base64=request.audio,
            text_message=request.message,
            api_config=request.api_config,
            is_greeting=request.is_greeting,
            audio_id=request.audio_id,
            user_id=user_id,
        )
        return self._wrap_stream(source=source, run_id=run.id, session_id=request.session_id)

    async def _wrap_stream(self, *, source: AsyncGenerator[str, None], run_id: str, session_id: str) -> AsyncGenerator[str, None]:
        try:
            yield f"data: {json.dumps({'type': 'run', 'run_id': run_id}, ensure_ascii=False)}\n\n"
            async for chunk in source:
                yield chunk
            await self._run_service.succeed(run_id, {"session_id": session_id})
        except asyncio.CancelledError:
            await self._run_service.fail(run_id, "client_disconnected")
            raise
        except Exception as exc:
            safe_msg = safe_error_message(exc)
            await self._run_service.fail(run_id, safe_msg)
            yield f"data: {json.dumps({'type': 'error', 'content': safe_msg}, ensure_ascii=False)}\n\n"


voice_stream_use_cases = VoiceStreamUseCases()
