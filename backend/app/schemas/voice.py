"""语音面试 HTTP 请求与响应模型。"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from app.config import get_settings
from app.domain.interview_rounds import resolve_max_questions, resolve_round_type
from app.schemas.job_context import JobContextSnapshot
from app.schemas.schemas import InterviewCandidateQuestion


def _wav_duration_seconds(data: bytes) -> float | None:
    """处理WAV时长秒数相关后端逻辑。"""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    byte_rate = int.from_bytes(data[28:32], "little", signed=False)
    if byte_rate <= 0:
        return None
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little", signed=False)
        if chunk_id == b"data":
            return chunk_size / byte_rate
        offset += 8 + chunk_size + (chunk_size % 2)
    return None


class VoiceStartRequest(BaseModel):
    """语音面试开始请求。"""

    thread_id: str = Field(..., description="会话ID")
    api_config: Dict[str, Any] = Field(..., description="API配置")
    resume_content: Optional[str] = None
    resume_filename: Optional[str] = None
    job_description: Optional[str] = None
    company_info: Optional[str] = None
    job_context_snapshot: Optional[JobContextSnapshot] = None
    max_questions: int | None = Field(default=None, ge=1, le=20)
    round_type: str = Field(default="tech_initial", description="面试类型")
    question_bank_count: int = Field(default=0, ge=0, le=20)
    experience_questions: List[InterviewCandidateQuestion] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def resolve_question_defaults(self) -> "VoiceStartRequest":
        """解析题目默认值相关后端逻辑。"""
        self.round_type = resolve_round_type(self.round_type)
        self.max_questions = resolve_max_questions(self.round_type, self.max_questions)
        return self


class VoiceChatRequest(BaseModel):
    """语音对话请求，并在模型调用前限制音频体积、格式和 WAV 时长。"""

    audio: Optional[str] = None
    message: Optional[str] = None
    system_prompt: str
    session_id: str
    api_config: Dict[str, Any]
    history: List[Dict[str, Any]] = Field(default_factory=list)
    is_greeting: bool = False
    audio_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_audio_boundary(self) -> "VoiceChatRequest":
        """校验音频相关后端逻辑。"""
        if self.audio is None:
            return self
        encoded = self.audio.strip()
        if not encoded:
            raise ValueError("音频内容为空，请重新录制")
        settings = get_settings()
        estimated_bytes = (len(encoded) * 3) // 4
        if estimated_bytes > settings.voice_audio_max_bytes + 3:
            raise ValueError("录音体积过大，请缩短后重新录制")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("音频格式无效，请重新录制") from exc
        if not decoded:
            raise ValueError("音频内容为空，请重新录制")
        if len(decoded) > settings.voice_audio_max_bytes:
            raise ValueError("录音体积过大，请缩短后重新录制")
        duration = _wav_duration_seconds(decoded)
        if duration is not None and duration > settings.voice_audio_max_duration_seconds:
            raise ValueError(
                f"单次录音不能超过 {settings.voice_audio_max_duration_seconds} 秒，请分段回答"
            )
        return self


class VoiceStartResponse(BaseModel):
    """语音面试启动或恢复响应。"""

    success: bool
    session_id: str
    system_prompt: str
    first_question: str
    audio: Optional[str] = None
    greeting_text: Optional[str] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)
    round_index: int = 1
    question_count: int = 0
    max_questions: int = 10


class VoiceCloneRequest(BaseModel):
    """克隆文字会话为语音会话的请求。"""

    source_session_id: str
    max_questions: Optional[int] = Field(default=None, ge=1, le=20)
