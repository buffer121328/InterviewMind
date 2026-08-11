"""MiMo 拆分语音网关契约测试。"""

from types import SimpleNamespace

import pytest

from ai.llm.mimo import MimoVoiceGateway


class _FakeCompletions:
    """记录 OpenAI-compatible 请求并返回测试指定响应。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        """返回下一条响应并保留不含真实凭据的调用参数。"""
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _response(*, content: str = "", audio=None):
    """构造最小 OpenAI chat completion 响应。"""
    message = SimpleNamespace(content=content, audio=audio)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def _install_client(monkeypatch, gateway: MimoVoiceGateway, responses):
    """把网关外部调用替换为确定性的内存客户端。"""
    completions = _FakeCompletions(responses)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(gateway, "_get_client", lambda *_args, **_kwargs: client)
    return completions


@pytest.mark.asyncio
async def test_asr_uses_fixed_model_and_data_url(monkeypatch):
    """ASR 始终发送 WAV data URL，模型名不接受前端覆盖。"""
    gateway = MimoVoiceGateway()
    completions = _install_client(monkeypatch, gateway, [_response(content="K8s 与 RAG")])

    text = await gateway.transcribe("YWJj", "test-key", "https://api.example.test/v1")

    assert text == "K8s 与 RAG"
    call = completions.calls[0]
    assert call["model"] == "mimo-v2.5-asr"
    audio = call["messages"][0]["content"][0]
    assert audio == {
        "type": "input_audio",
        "input_audio": {"data": "data:audio/wav;base64,YWJj"},
    }


@pytest.mark.asyncio
async def test_tts_uses_assistant_text_and_wav_audio_contract(monkeypatch):
    """TTS 把风格放 user、正文放 assistant，并读取字典 audio.data。"""
    gateway = MimoVoiceGateway()
    completions = _install_client(monkeypatch, gateway, [_response(audio={"data": "UklGRg=="})])

    audio = await gateway.synthesize(
        "你好，我是面试官。",
        "test-key",
        "https://api.example.test/v1",
        style="自然语气",
        voice="Chloe",
    )

    assert audio == "UklGRg=="
    call = completions.calls[0]
    assert call["model"] == "mimo-v2.5-tts"
    assert call["messages"] == [
        {"role": "user", "content": "自然语气"},
        {"role": "assistant", "content": "你好，我是面试官。"},
    ]
    assert call["audio"] == {"format": "wav", "voice": "Chloe"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "response", "message"),
    [
        ("transcribe", _response(content=""), "ASR 未返回文本"),
        ("synthesize", _response(audio={}), "TTS 未返回音频"),
    ],
)
async def test_empty_provider_outputs_are_rejected(monkeypatch, method, response, message):
    """Provider 返回空文本或空音频时必须显式失败。"""
    gateway = MimoVoiceGateway()
    _install_client(monkeypatch, gateway, [response])

    with pytest.raises(ValueError, match=message):
        if method == "transcribe":
            await gateway.transcribe("YWJj", "test-key")
        else:
            await gateway.synthesize("你好", "test-key")


def test_private_base_url_is_rejected_when_private_models_are_disabled(monkeypatch):
    """公网部署配置下，MiMo 网关沿用统一 URL 安全校验。"""
    gateway = MimoVoiceGateway()
    monkeypatch.setattr(
        "ai.llm.mimo.get_settings",
        lambda: SimpleNamespace(allow_private_model_base_urls=False),
    )

    with pytest.raises(ValueError):
        gateway._get_client("test-key", "http://127.0.0.1:8000/v1", timeout=1)
