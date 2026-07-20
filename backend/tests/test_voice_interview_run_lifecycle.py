"""语音面试生成接入持久化 AgentRun。"""

import json
from types import SimpleNamespace

import pytest

from app.workflows.interview import voice_stream
from app.workflows.interview.voice_stream import VoiceStreamUseCases
from app.schemas.voice import VoiceChatRequest
from app.infrastructure.runtime.agent_runs.service import TASK_TYPE_VOICE_INTERVIEW_TURN, get_task_definition


def _agent_run_events(chunks):
    events = []
    for chunk in chunks:
        if not chunk.startswith("data: "):
            continue
        outer = json.loads(chunk.removeprefix("data: ").strip())
        if outer.get("type") != "agent_run_event":
            continue
        content = outer.get("content")
        events.append(json.loads(content) if isinstance(content, str) else content)
    return events


class _FakeRunService:
    def __init__(self):
        self.created = []
        self.stages = []
        self.succeeded = []
        self.failed = []

    async def create_or_get(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="voice-run-1"), True

    async def claim(self, run_id):
        assert run_id == "voice-run-1"
        return SimpleNamespace(id=run_id), {}

    async def mark_stage(self, run_id, stage):
        self.stages.append((run_id, stage))

    async def succeed(self, run_id, result):
        self.succeeded.append((run_id, result))

    async def fail(self, run_id, message):
        self.failed.append((run_id, message))


async def _fake_voice_chunks(**_kwargs):
    yield 'data: {"type":"token","content":"你好"}\n\n'
    yield 'data: {"type":"done","content":"[DONE]"}\n\n'


def test_voice_interview_turn_task_definition_is_registered():
    definition = get_task_definition(TASK_TYPE_VOICE_INTERVIEW_TURN)
    assert definition["title"] == "生成语音面试回复"
    assert ("generating_response", "生成语音面试回复") in definition["steps"]


@pytest.mark.asyncio
async def test_voice_chat_stream_creates_and_completes_agent_run(monkeypatch):
    use_cases = VoiceStreamUseCases()
    fake_run_service = _FakeRunService()
    use_cases._run_service = fake_run_service
    monkeypatch.setattr(voice_stream, "process_voice_chat", _fake_voice_chunks)

    request = VoiceChatRequest(
        session_id="voice-session-1",
        system_prompt="你是面试官",
        history=[],
        message="我的回答",
        api_config={"voice": {"api_key": "x"}},
        audio_id="audio-1",
    )

    generator = await use_cases.stream_voice_chat(request=request, user_id="user-1")
    chunks = [chunk async for chunk in generator]

    assert fake_run_service.created[0]["task_type"] == TASK_TYPE_VOICE_INTERVIEW_TURN
    assert fake_run_service.created[0]["payload"]["session_id"] == "voice-session-1"
    assert fake_run_service.stages == [("voice-run-1", "generating_response")]
    assert fake_run_service.succeeded == [("voice-run-1", {"session_id": "voice-session-1"})]
    assert fake_run_service.failed == []
    run_events = _agent_run_events(chunks)
    assert {event["type"] for event in run_events} >= {"run.started", "run.completed"}
    assert all(event["run_id"] == "voice-run-1" for event in run_events)
    assert [event["sequence"] for event in run_events] == [1, 2]
    assert [event["event_id"] for event in run_events] == ["inline:voice-run-1:1", "inline:voice-run-1:2"]


async def _cancelled_voice_chunks(**_kwargs):
    yield 'data: {"type":"token","content":"你好"}\n\n'


@pytest.mark.asyncio
async def test_voice_chat_disconnect_marks_run_failed_not_cancelled(monkeypatch):
    import asyncio

    use_cases = VoiceStreamUseCases()
    fake_run_service = _FakeRunService()
    use_cases._run_service = fake_run_service
    monkeypatch.setattr(voice_stream, "process_voice_chat", _cancelled_voice_chunks)

    request = VoiceChatRequest(
        session_id="voice-session-1",
        system_prompt="你是面试官",
        history=[],
        message="我的回答",
        api_config={"voice": {"api_key": "x"}},
    )

    generator = await use_cases.stream_voice_chat(request=request, user_id="user-1")
    await generator.__anext__()
    with pytest.raises(asyncio.CancelledError):
        await generator.athrow(asyncio.CancelledError())

    assert fake_run_service.failed == [("voice-run-1", "client_disconnected")]
    assert fake_run_service.succeeded == []
