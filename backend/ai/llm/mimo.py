"""小米 MiMo 语音拆分模型客户端（OpenAI 兼容）。"""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter
from typing import Any

from app.config import get_settings
from app.security.url_security import validate_outbound_url
from observability import (
    extract_token_usage,
    measure_model_input,
    provider_observability_metadata,
    record_model_event,
)

MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_ASR_MODEL = "mimo-v2.5-asr"
MIMO_CHAT_MODEL = "mimo-v2.5"
MIMO_TTS_MODEL = "mimo-v2.5-tts"


def _message_content(message: Any) -> str:
    """读取 OpenAI-compatible 消息文本，不保留或记录完整响应对象。"""
    content = getattr(message, "content", None)
    return str(content or "").strip()


def _audio_data(message: Any) -> str:
    """兼容字典和 SDK 对象两种 TTS audio 响应形态。"""
    audio = getattr(message, "audio", None)
    data = audio.get("data") if isinstance(audio, dict) else getattr(audio, "data", None)
    value = str(data or "")
    if ";base64," in value:
        value = value.split(";base64,", 1)[1]
    return value.strip()


class MimoVoiceGateway:
    """封装 MiMo ASR、文本对话和 TTS，并统一 URL、超时与观测边界。"""

    def _get_client(self, api_key: str, base_url: str, *, timeout: float) -> Any:
        """校验请求端点后创建无 SDK 自动重试的短生命周期客户端。"""
        from openai import AsyncOpenAI

        settings = get_settings()
        validate_outbound_url(
            base_url,
            allow_private=settings.allow_private_model_base_urls,
        )
        return AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )

    @staticmethod
    def _config(api_key: str, base_url: str, model: str) -> dict[str, str]:
        """构造只用于安全观测元数据的 provider 配置。"""
        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "provider": "mimo",
            "integration": "openai_compatible",
            "pricing_key": model,
        }

    async def _create(
        self,
        *,
        operation: str,
        model: str,
        messages: Sequence[dict[str, Any]],
        api_key: str,
        base_url: str,
        timeout: float,
        **options: Any,
    ) -> Any:
        """执行单次 MiMo 调用，并仅记录不含 Key、正文和音频的安全指标。"""
        if not api_key:
            raise ValueError("未配置语音模型，请在设置中配置小米 MiMo")
        normalized_url = (base_url or MIMO_BASE_URL).rstrip("/")
        config = self._config(api_key, normalized_url, model)
        metadata = provider_observability_metadata(config)
        input_metrics = measure_model_input(
            messages,
            chars_per_token=get_settings().llm_estimated_chars_per_token,
        )
        started = perf_counter()
        record_model_event(
            event_type=f"voice.{operation}.started",
            channel="mimo",
            model_name=model,
            **metadata,
            **input_metrics,
        )
        try:
            client = self._get_client(api_key, normalized_url, timeout=timeout)
            response = await client.chat.completions.create(
                model=model,
                messages=list(messages),
                timeout=timeout,
                **options,
            )
        except Exception as exc:
            record_model_event(
                event_type=f"voice.{operation}.failed",
                channel="mimo",
                model_name=model,
                **metadata,
                duration_ms=max(0, int((perf_counter() - started) * 1000)),
                error_type=type(exc).__name__,
                **input_metrics,
            )
            raise
        record_model_event(
            event_type=f"voice.{operation}.completed",
            channel="mimo",
            model_name=model,
            **metadata,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            **input_metrics,
            **extract_token_usage(response),
        )
        return response

    async def transcribe(
        self,
        audio_base64: str,
        api_key: str,
        base_url: str = MIMO_BASE_URL,
        *,
        audio_format: str = "wav",
    ) -> str:
        """把请求内存中的 WAV base64 转为文本，不缓存或记录音频明文。"""
        if not audio_base64:
            raise ValueError("ASR 音频为空")
        response = await self._create(
            operation="asr",
            model=MIMO_ASR_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:audio/{audio_format};base64,{audio_base64}",
                            },
                        }
                    ],
                }
            ],
            api_key=api_key,
            base_url=base_url,
            timeout=get_settings().mimo_asr_timeout_seconds,
        )
        text = _message_content(response.choices[0].message)
        if not text:
            raise ValueError("ASR 未返回文本")
        return text

    async def chat_text(
        self,
        messages: list[dict[str, Any]],
        api_key: str,
        base_url: str = MIMO_BASE_URL,
    ) -> str:
        """使用 MiMo 文本模型生成面试官回复，拒绝空消息和空响应。"""
        if not messages:
            raise ValueError("文本对话消息为空")
        response = await self._create(
            operation="chat",
            model=MIMO_CHAT_MODEL,
            messages=messages,
            api_key=api_key,
            base_url=base_url,
            timeout=get_settings().llm_request_timeout_seconds,
        )
        text = _message_content(response.choices[0].message)
        if not text:
            raise ValueError("文本对话未返回内容")
        return text

    async def synthesize(
        self,
        text: str,
        api_key: str,
        base_url: str = MIMO_BASE_URL,
        *,
        style: str = "自然、专业、克制的中文面试官语气，语速适中。",
        voice: str | None = None,
    ) -> str:
        """把回复文本合成为 WAV base64；文本放 assistant 角色以符合 MiMo TTS 契约。"""
        if not text.strip():
            raise ValueError("TTS 文本为空")
        messages: list[dict[str, str]] = []
        if style.strip():
            messages.append({"role": "user", "content": style.strip()})
        messages.append({"role": "assistant", "content": text})
        response = await self._create(
            operation="tts",
            model=MIMO_TTS_MODEL,
            messages=messages,
            api_key=api_key,
            base_url=base_url,
            timeout=get_settings().mimo_tts_timeout_seconds,
            audio={"format": "wav", "voice": voice or get_settings().mimo_voice},
        )
        data = _audio_data(response.choices[0].message)
        if not data:
            raise ValueError("TTS 未返回音频")
        return data


mimo_voice_gateway = MimoVoiceGateway()
