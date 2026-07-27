"""语音面试流式回复用例。"""

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.schemas.voice import VoiceChatRequest
from app.db.repositories.session.session_repo import SessionRepo
from ai.runtime.agent_runs.event_stream import build_run_event_envelope
from app.domain.agent_runs import TASK_TYPE_VOICE_INTERVIEW_TURN
from ai.runtime.agent_runs.service import AgentRunService
from ai.agents.interview.voice_interview import process_voice_chat
from app.security.security import safe_error_message


@dataclass(slots=True)
class VoiceStreamUseCaseError(Exception):
    """语音面试流式用例异常。"""

    message: str
    status_code: int = 409


class VoiceStreamUseCases:
    """语音面试流式应用服务。"""

    def __init__(self) -> None:
        """初始化 `VoiceStreamUseCases` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._run_service = AgentRunService()
        self._session_repo = SessionRepo()

    async def stream_voice_chat(self, *, request: VoiceChatRequest, user_id: str) -> AsyncGenerator[str, None]:
        """流式执行语音面试回复并发出可恢复事件；模型调用、音频内容和会话 owner 均遵循统一安全与审计边界。

        Args:
            request: 请求对象。
            user_id: 当前用户标识。
        """
        session = await self._session_repo.get_session(request.session_id, user_id=user_id)
        if session is None:
            raise VoiceStreamUseCaseError(message="会话不存在或无权访问", status_code=404)

        run, _ = await self._run_service.create_or_get(
            user_id=user_id,
            task_type=TASK_TYPE_VOICE_INTERVIEW_TURN,
            idempotency_key=f"voice-turn:{request.session_id}:{request.audio_id or 'text'}:{id(request)}",
            session_id=request.session_id,
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
        """包装流式事件生成器，统一补充运行上下文和错误收尾事件。

        Args:
            source: 经过类型边界校验的 `source`；其格式和可选值由参数类型及调用流程约束。
            run_id: 运行标识。
            session_id: 会话标识。
        """
        run_event_sequence = 0

        def run_event(event_type: str, stage: str | None = None, payload: dict | None = None) -> str:
            """运行 event，沿用既有任务状态、重试和持久化边界，不在辅助函数中绕过审批或 owner 校验。

            Args:
                event_type: 经过类型边界校验的 `event_type`；其格式和可选值由参数类型及调用流程约束。
                stage: 经过类型边界校验的 `stage`；其格式和可选值由参数类型及调用流程约束。
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
