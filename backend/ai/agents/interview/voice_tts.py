"""语音面试 TTS 辅助函数。"""

import base64
import logging
from typing import Any, Optional

from ai.agents.interview.voice_utils import pcm_to_wav
from ai.llm import llms
from ai.prompts.voice import build_tts_system_prompt

logger = logging.getLogger(__name__)


async def generate_greeting_audio(text: str, api_config: dict[str, Any]) -> tuple[Optional[str], str]:
    """使用 Omni 生成开场白音频。"""
    try:
        messages = [
            {
                "role": "system",
                "content": build_tts_system_prompt(),
            },
            {
                "role": "user",
                "content": f"请朗读以下内容：\n\n{text}",
            },
        ]

        completion = llms.model_gateway.stream_voice_chat_completions(
            api_config,
            messages=messages,
        )

        audio_chunks = []
        text_chunks = []

        async for chunk in completion:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    text_chunks.append(delta.content)
                if hasattr(delta, "audio") and delta.audio:
                    audio_data = None
                    if isinstance(delta.audio, dict):
                        audio_data = delta.audio.get("data")
                    elif hasattr(delta.audio, "data"):
                        audio_data = delta.audio.data
                    if audio_data:
                        audio_chunks.append(audio_data)

        generated_text = "".join(text_chunks)

        if not audio_chunks:
            return None, generated_text or text

        combined_base64 = "".join(audio_chunks)
        try:
            pcm_data = base64.b64decode(combined_base64)
            wav_data = pcm_to_wav(pcm_data)
            result = base64.b64encode(wav_data).decode("utf-8")
            return result, generated_text or text
        except Exception as conv_err:
            logger.warning("[Voice] PCM 转 WAV 失败: %s", conv_err)
            return combined_base64, generated_text or text

    except Exception as e:
        logger.error("[Voice] 生成开场白音频失败: %s", e)
        return None, text
