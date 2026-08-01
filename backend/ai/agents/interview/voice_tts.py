"""语音面试 TTS 辅助函数。"""

import base64
from typing import Any, Optional

from ai.agents.interview.voice_utils import pcm_to_wav
from ai.llm.mimo import MIMO_BASE_URL, mimo_voice_gateway


async def generate_greeting_audio(text: str, api_config: dict[str, Any]) -> tuple[Optional[str], str]:
    """使用 MiMo TTS 生成开场白，并避免给完整 WAV 重复添加文件头。"""
    mimo = (api_config or {}).get("mimo") or {}
    if not mimo.get("api_key"):
        return None, text
    audio_data = await mimo_voice_gateway.synthesize(
        text,
        mimo["api_key"],
        mimo.get("base_url") or MIMO_BASE_URL,
    )
    decoded = base64.b64decode(audio_data, validate=True)
    if decoded[:4] == b"RIFF" and decoded[8:12] == b"WAVE":
        return audio_data, text
    wav_data = pcm_to_wav(decoded)
    return base64.b64encode(wav_data).decode("utf-8"), text
