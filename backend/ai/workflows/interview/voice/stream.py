"""语音面试流式回复用例。"""

import hashlib
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from ai.agents.interview.voice.flow import process_voice_chat
from ai.runtime.agent_runs.service import AgentRunService
from ai.runtime.harness.contracts import StreamExecution
from ai.runtime.harness.drivers import StreamDriver, StreamDriverConflict
from app.db.repositories.session.session_repo import SessionRepo
from app.domain.agent_definitions import get_agent_definition
from app.domain.agent_runs import TASK_TYPE_VOICE_INTERVIEW_TURN
from app.schemas.interview.voice import VoiceChatRequest


@dataclass(slots=True)
class VoiceStreamUseCaseError(Exception):
    """语音面试流式用例异常。"""

    # 单条消息。
    # 单条消息。
    message: str
    # status_code，整数类型。
    # 状态码。
    status_code: int = 409


class VoiceStreamUseCases:
    """语音面试流式应用服务。"""

    def __init__(self) -> None:
        """初始化受 owner scope 约束的语音面试流依赖。"""

        self._run_service = AgentRunService()
        self._session_repo = SessionRepo()

    async def stream_voice_chat(
        self,
        *,
        request: VoiceChatRequest,
        user_id: str,
    ) -> AsyncGenerator[str, None]:
        """通过统一 StreamDriver 执行语音 SSE 生命周期。

        Args:
            request: 请求对象。
            user_id: 用户 ID，所有者范围限定。
        """

        session = await self._session_repo.get_session(request.session_id, user_id=user_id)
        if session is None:
            raise VoiceStreamUseCaseError(message="会话不存在或无权访问", status_code=404)

        metadata = getattr(session, "metadata", None)
        question_index = int(getattr(metadata, "question_count", 0) or 0)
        request_fingerprint = self._request_fingerprint(request)
        idempotency_key = (
            f"voice-turn:{request.session_id}:{question_index}:"
            f"{len(request.history)}:{request_fingerprint}"
        )

        async def stream_factory(run_id: str) -> StreamExecution:
            """构造语音领域 stream；终态始终由 StreamDriver 持久化。

            Args:
                run_id: 任务运行 ID。
            """

            return StreamExecution(
                source=process_voice_chat(
                    session_id=request.session_id,
                    system_prompt=request.system_prompt,
                    history=request.history,
                    audio_base64=request.audio,
                    text_message=request.message,
                    api_config=request.api_config,
                    is_greeting=request.is_greeting,
                    audio_id=request.audio_id,
                    user_id=user_id,
                    run_id=run_id,
                ),
                result=lambda: {"session_id": request.session_id},
                preamble=(
                    f"data: {json.dumps({'type': 'run', 'run_id': run_id}, ensure_ascii=False)}\n\n",
                ),
                encode_run_event=self._encode_run_event,
                encode_error=self._encode_error,
                detect_error=self._detect_error_event,
            )

        driver = StreamDriver(service=self._run_service)
        try:
            return await driver.start(
                task_type=TASK_TYPE_VOICE_INTERVIEW_TURN,
                payload={
                    "session_id": request.session_id,
                    "has_audio": bool(request.audio),
                    "has_text": bool(request.message),
                    "is_greeting": bool(request.is_greeting),
                },
                user_id=user_id,
                session_id=request.session_id,
                idempotency_key=idempotency_key,
                initial_stage="generating_response",
                stream_factory=stream_factory,
                requires_global_gate=(
                    get_agent_definition(TASK_TYPE_VOICE_INTERVIEW_TURN).run_gate_policy
                    == "global"
                ),
                fallback_run_event_encoder=self._encode_run_event,
                fallback_error_encoder=self._encode_error,
            )
        except StreamDriverConflict as exc:
            raise VoiceStreamUseCaseError(message=exc.message) from exc

    @staticmethod
    def _request_fingerprint(request: VoiceChatRequest) -> str:
        """派生不落库的语音提交标识，避免 object id 造成重复执行。

        Args:
            request: 请求对象。
        """

        source = request.audio_id or request.message or request.audio or "greeting"
        material = f"{request.is_greeting}:{source}".encode()
        return hashlib.sha256(material).hexdigest()[:20]

    @staticmethod
    def _encode_run_event(envelope: dict) -> str:
        """编码保持兼容的语音 lifecycle SSE event。

        Args:
            envelope: 信封数据。
        """

        return (
            f"data: {json.dumps({'type': 'agent_run_event', 'content': envelope}, ensure_ascii=False)}\n\n"
        )

    @staticmethod
    def _encode_error(message: str) -> str:
        """编码保持兼容的语音错误 SSE event。

        Args:
            message: 单条消息。
        """

        return (
            f"data: {json.dumps({'type': 'error', 'content': message}, ensure_ascii=False)}\n\n"
        )

    @staticmethod
    def _detect_error_event(chunk: str) -> str | None:
        """把业务 source 已映射的 error frame 收敛为 AgentRun failure。

        Args:
            chunk: 分片或 chunk 对象。
        """

        for line in chunk.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line.removeprefix("data: "))
            except json.JSONDecodeError:
                continue
            if event.get("type") != "error":
                continue
            return str(event.get("content") or event.get("message") or "语音面试流执行失败")
        return None


voice_stream_use_cases = VoiceStreamUseCases()
