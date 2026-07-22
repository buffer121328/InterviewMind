"""语音面试流式回复用例。"""

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.schemas.voice import VoiceChatRequest
from app.infrastructure.runtime.agent_runs.event_stream import build_run_event_envelope
from app.domain.agent_runs import TASK_TYPE_VOICE_INTERVIEW_TURN
from app.infrastructure.runtime.agent_runs.service import AgentRunService
from app.agents.interview.voice_interview import process_voice_chat
from app.infrastructure.security.security import safe_error_message


@dataclass(slots=True)
class VoiceStreamUseCaseError(Exception):
    """语音面试流式用例异常。"""

    message: str


class VoiceStreamUseCases:
    """语音面试流式应用服务。"""

    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self._run_service = AgentRunService()

    async def stream_voice_chat(self, *, request: VoiceChatRequest, user_id: str) -> AsyncGenerator[str, None]:
        """流式处理 `voice chat`。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
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
            run_id=run.id,
        )
        return self._wrap_stream(source=source, run_id=run.id, session_id=request.session_id)

    async def _wrap_stream(self, *, source: AsyncGenerator[str, None], run_id: str, session_id: str) -> AsyncGenerator[str, None]:
        """异步执行 `_wrap_stream` 相关逻辑。

        Args:
            source: 调用方传入的 `source` 参数。
            run_id: 运行标识。
            session_id: 会话标识。
        """
        run_event_sequence = 0

        def run_event(event_type: str, stage: str | None = None, payload: dict | None = None) -> str:
            """运行 `event`。

            Args:
                event_type: 调用方传入的 `event_type` 参数。
                stage: 调用方传入的 `stage` 参数。
                payload: 请求载荷。
            """
            nonlocal run_event_sequence
            run_event_sequence += 1
            envelope = build_run_event_envelope(
                run_id=run_id,
                event_type=event_type,
                stage=stage,
                payload=payload,
                sequence=run_event_sequence,
                event_id=f"inline:{run_id}:{run_event_sequence}",
            )
            return f"data: {json.dumps({'type': 'agent_run_event', 'content': envelope}, ensure_ascii=False)}\n\n"

        try:
            yield f"data: {json.dumps({'type': 'run', 'run_id': run_id}, ensure_ascii=False)}\n\n"
            yield run_event("run.started", "generating_response")
            async for chunk in source:
                yield chunk
            await self._run_service.succeed(run_id, {"session_id": session_id})
            yield run_event("run.completed", "succeeded")
        except asyncio.CancelledError:
            await self._run_service.fail(run_id, "client_disconnected")
            raise
        except Exception as exc:
            safe_msg = safe_error_message(exc)
            await self._run_service.fail(run_id, safe_msg)
            yield run_event("run.failed", None, {"message": safe_msg})
            yield f"data: {json.dumps({'type': 'error', 'content': safe_msg}, ensure_ascii=False)}\n\n"


voice_stream_use_cases = VoiceStreamUseCases()
