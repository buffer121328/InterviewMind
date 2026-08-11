"""语音面试 MiMo 拆分链路验收测试。"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ai.agents.interview.voice import flow as voice_interview


def _event_type(frame: str) -> str:
    """读取单个测试 SSE frame 的事件类型。"""
    return json.loads(frame.removeprefix("data: ").strip())["type"]


@pytest.mark.asyncio
async def test_process_voice_chat_requires_mimo_key_before_routing(monkeypatch):
    """缺少 MiMo Key 时直接返回明确错误，不进入任何语音节点。"""
    async def fail_node(_state):
        raise AssertionError("missing config must fail before routing")
        yield ""  # pragma: no cover

    monkeypatch.setattr(voice_interview, "node_greeting", fail_node)
    monkeypatch.setattr(voice_interview, "node_responder", fail_node)
    source = voice_interview.process_voice_chat(
        session_id="voice-1",
        system_prompt="prompt",
        history=[],
        audio_base64=None,
        text_message="你好",
        api_config={},
    )

    frames = [frame async for frame in source]

    assert len(frames) == 1
    payload = json.loads(frames[0].removeprefix("data: ").strip())
    assert payload["type"] == "error"
    assert payload["content"] == "未配置语音模型，请在设置中配置小米 MiMo"


@pytest.mark.asyncio
async def test_audio_turn_uses_asr_text_then_emits_text_audio_done(monkeypatch):
    """有音频时浏览器文本不进入对话模型，事件保持 text→audio→done。"""
    calls: list[tuple[str, object]] = []

    class _SessionRepo:
        """提供语音节点所需的最小会话持久化边界。"""

        async def get_session(self, *_args, **_kwargs):
            return SimpleNamespace(metadata=SimpleNamespace(question_count=0))

        async def get_interview_plan(self, *_args, **_kwargs):
            return [{"content": "请介绍项目"}, {"content": "请说明架构"}]

        async def update_session_question_count(self, _session_id, index):
            calls.append(("progress", index))

    async def transcribe(audio, *_args, **_kwargs):
        calls.append(("asr", audio))
        return "ASR 专业术语"

    async def chat_text(messages, *_args, **_kwargs):
        calls.append(("chat", messages[-1]["content"]))
        return "请继续说明技术取舍。"

    async def synthesize(text, *_args, **_kwargs):
        calls.append(("tts", text))
        return "UklGRg=="

    async def save_message(*_args, **_kwargs):
        return None

    def progress(*_args, **_kwargs):
        return {
            "current_q_idx": 0,
            "follow_up_count": 0,
            "last_q_text": "请介绍项目",
            "is_complete": False,
        }

    monkeypatch.setattr(voice_interview, "SessionRepo", _SessionRepo)
    monkeypatch.setattr(voice_interview, "save_message_async", save_message)
    monkeypatch.setattr(voice_interview, "calculate_interview_progress", progress)
    monkeypatch.setattr(voice_interview.mimo_voice_gateway, "transcribe", transcribe)
    monkeypatch.setattr(voice_interview.mimo_voice_gateway, "chat_text", chat_text)
    monkeypatch.setattr(voice_interview.mimo_voice_gateway, "synthesize", synthesize)

    state = {
        "session_id": "voice-1",
        "user_id": "user-1",
        "run_id": None,
        "api_config": {"mimo": {"api_key": "test", "base_url": "https://api.example.test/v1"}},
        "interview_plan": [],
        "system_prompt": "prompt",
        "history": [],
        "current_phase": "conversation",
        "audio_base64": "YWJj",
        "text_message": "浏览器转录",
        "audio_id": "audio-1",
    }
    frames = [frame async for frame in voice_interview.node_responder(state)]
    event_types = [_event_type(frame) for frame in frames]

    assert calls[:3] == [
        ("asr", "YWJj"),
        ("chat", "ASR 专业术语"),
        ("tts", "请继续说明技术取舍。"),
    ]
    assert event_types.index("text") < event_types.index("audio") < event_types.index("done")


@pytest.mark.asyncio
async def test_process_voice_chat_preserves_explicit_greeting_route(monkeypatch):
    """迁移后仍只允许显式 is_greeting 选择开场白节点。"""
    routed: list[str] = []

    class _Observation:
        """提供 process 观测上下文所需的最小输出接口。"""

        def set_output(self, _payload):
            return None

    @asynccontextmanager
    async def observation(**_kwargs):
        yield _Observation()

    async def greeting(_state):
        routed.append("greeting")
        yield 'data: {"type":"done"}\n\n'

    monkeypatch.setattr(voice_interview, "agent_observation", observation)
    monkeypatch.setattr(voice_interview, "node_greeting", greeting)
    source = voice_interview.process_voice_chat(
        session_id="voice-1",
        system_prompt="prompt",
        history=[],
        audio_base64=None,
        text_message="开场白",
        api_config={"mimo": {"api_key": "test"}},
        is_greeting=True,
    )

    assert [_event_type(frame) for frame in [item async for item in source]] == ["done"]
    assert routed == ["greeting"]
