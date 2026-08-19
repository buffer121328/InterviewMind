"""语音面试 HTTP 请求与响应模型。"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from app.config import get_settings
from app.domain.interview_report_modes import InterviewReportMode
from app.domain.interview_rounds import resolve_max_questions, resolve_round_type
from app.schemas.jobs.job_context import JobContextSnapshot


def _wav_duration_seconds(data: bytes) -> float | None:
    """解析 WAV 二进制返回音频时长（秒）；非 WAV 或无法解析返回 None。

    Args:
        data: WAV 音频的原始二进制内容
    """
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
    resume_content: Optional[str] = Field(default=None, description="简历全文内容")
    resume_filename: Optional[str] = Field(default=None, description="简历文件名")
    job_description: Optional[str] = Field(default=None, description="职位描述")
    company_info: Optional[str] = Field(default=None, description="公司信息")
    job_context_snapshot: Optional[JobContextSnapshot] = Field(default=None, description="来源岗位与实际编辑上下文快照")
    max_questions: int | None = Field(default=None, ge=1, le=20, description="最大问题数量；不传时按面试类型默认")
    round_type: str = Field(default="tech_initial", description="面试类型")
    report_mode: InterviewReportMode = Field(default=InterviewReportMode.DEEP, description="报告模式；旧调用缺省为 deep")
    question_bank_count: int = Field(default=0, ge=0, le=20, description="从个人题库抽取的题数")

    @model_validator(mode="after")
    def resolve_question_defaults(self) -> "VoiceStartRequest":
        """校验后解析轮次类型与最大题数并补全默认值。"""
        self.round_type = resolve_round_type(self.round_type)
        self.max_questions = resolve_max_questions(self.round_type, self.max_questions)
        return self


class VoiceChatRequest(BaseModel):
    """语音对话请求，并在模型调用前限制音频体积、格式和 WAV 时长。"""

    audio: Optional[str] = Field(default=None, description="base64 编码的音频内容（可选）")
    message: Optional[str] = Field(default=None, description="文本消息内容（可选）")
    system_prompt: str = Field(..., description="系统提示词")
    session_id: str = Field(..., description="会话 ID")
    api_config: Dict[str, Any] = Field(..., description="用户自定义 API 配置")
    history: List[Dict[str, Any]] = Field(default_factory=list, description="对话历史")
    is_greeting: bool = Field(default=False, description="是否为开场问候")
    audio_id: Optional[str] = Field(default=None, description="音频 ID（可选）")

    @model_validator(mode="after")
    def validate_audio_boundary(self) -> "VoiceChatRequest":
        """校验音频非空、体积与 WAV 时长在服务端限制内，不通过则拒绝请求。"""
        if self.audio is None:
            return self
        encoded = self.audio.strip()
        if not encoded:
            raise ValueError("音频内容为空，请重新录制")
        settings = get_settings()
        estimated_bytes = (len(encoded) * 3) // 4  # ① 估算 base64 解码后的体积
        if estimated_bytes > settings.voice_audio_max_bytes + 3:
            raise ValueError("录音体积过大，请缩短后重新录制")
        try:
            decoded = base64.b64decode(encoded, validate=True)  # ② 解码并校验 base64 格式
        except (binascii.Error, ValueError) as exc:
            raise ValueError("音频格式无效，请重新录制") from exc
        if not decoded:
            raise ValueError("音频内容为空，请重新录制")
        if len(decoded) > settings.voice_audio_max_bytes:
            raise ValueError("录音体积过大，请缩短后重新录制")
        duration = _wav_duration_seconds(decoded)  # ③ 解析 WAV 时长并做上限校验
        if duration is not None and duration > settings.voice_audio_max_duration_seconds:
            raise ValueError(
                f"单次录音不能超过 {settings.voice_audio_max_duration_seconds} 秒，请分段回答"
            )
        return self


class VoiceStartResponse(BaseModel):
    """语音面试启动或恢复响应。"""

    success: bool = Field(..., description="是否成功")
    session_id: str = Field(..., description="会话 ID")
    system_prompt: str = Field(..., description="系统提示词")
    first_question: str = Field(..., description="首题内容")
    audio: Optional[str] = Field(default=None, description="开场音频（可选）")
    greeting_text: Optional[str] = Field(default=None, description="问候文本（可选）")
    history: List[Dict[str, Any]] = Field(default_factory=list, description="对话历史")
    round_index: int = Field(default=1, description="当前轮次序号")
    question_count: int = Field(default=0, description="当前主线题目进度（已完成题数/下一题索引）")
    max_questions: int = Field(default=10, description="最大问题数量")


class VoiceCloneRequest(BaseModel):
    """克隆文字会话为语音会话的请求。"""

    source_session_id: str = Field(..., description="源文字会话 ID")
    max_questions: Optional[int] = Field(default=None, ge=1, le=20, description="最大问题数量；不传时按面试类型默认")
