"""语音面试生成接入持久化 AgentRun。"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ai.agents.interview.voice import flow as voice_interview
from ai.runtime.agent_runs.service import get_task_definition
from ai.workflows.interview import voice_stream
from ai.workflows.interview.voice_stream import VoiceStreamUseCases
from app.domain.agent_runs import TASK_TYPE_VOICE_INTERVIEW_TURN
from app.schemas.voice import VoiceChatRequest


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


class _FakeSessionRepo:
    async def get_session(self, *_args, **_kwargs):
        return SimpleNamespace()


class _MissingSessionRepo:
    async def get_session(self, *_args, **_kwargs):
        return None


async def _fake_voice_chunks(**_kwargs):
    yield 'data: {"type":"token","content":"你好"}\n\n'
    yield 'data: {"type":"done","content":"[DONE]"}\n\n'


@pytest.mark.asyncio
async def test_voice_chat_does_not_infer_greeting_from_empty_history_and_text(monkeypatch):
    """Only the explicit request flag may select TTS greeting mode."""

    routed_phases: list[str] = []

    class _Observation:
        def set_output(self, _payload):
            return None

    @asynccontextmanager
    async def fake_observation(**_kwargs):
        yield _Observation()

    def fake_route(state):
        routed_phases.append(state["current_phase"])
        return "responder"

    async def fake_responder(_state):
        yield 'data: {"type":"token","content":"正常回答"}\n\n'

    async def fail_if_greeting(_state):
        raise AssertionError("greeting node must require is_greeting=true")
        yield ""  # pragma: no cover

    monkeypatch.setattr(voice_interview, "agent_observation", fake_observation)
    monkeypatch.setattr(voice_interview, "route_voice_entry", fake_route)
    monkeypatch.setattr(voice_interview, "node_responder", fake_responder)
    monkeypatch.setattr(voice_interview, "node_greeting", fail_if_greeting)

    source = voice_interview.process_voice_chat(
        session_id="voice-session-1",
        system_prompt="你是面试官",
        history=[],
        audio_base64=None,
        text_message="普通文字回答",
        api_config={"mimo": {"api_key": "x"}},
        is_greeting=False,
        user_id="user-1",
    )

    assert [chunk async for chunk in source] == [
        'data: {"type":"token","content":"正常回答"}\n\n'
    ]
    assert routed_phases == ["conversation"]


def test_voice_interview_turn_task_definition_is_registered():
    definition = get_task_definition(TASK_TYPE_VOICE_INTERVIEW_TURN)
    assert definition["title"] == "生成语音面试回复"
    assert ("generating_response", "生成语音面试回复") in definition["steps"]


@pytest.mark.asyncio
async def test_voice_chat_rejects_unowned_session_before_creating_run():
    use_cases = VoiceStreamUseCases()
    fake_run_service = _FakeRunService()
    use_cases._run_service = fake_run_service
    use_cases._session_repo = _MissingSessionRepo()

    request = VoiceChatRequest(
        session_id="other-user-session",
        system_prompt="你是面试官",
        history=[],
        message="我的回答",
        api_config={"mimo": {"api_key": "x"}},
    )

    with pytest.raises(voice_stream.VoiceStreamUseCaseError) as exc_info:
        await use_cases.stream_voice_chat(request=request, user_id="user-1")

    assert exc_info.value.status_code == 404
    assert fake_run_service.created == []


@pytest.mark.asyncio
async def test_voice_chat_stream_creates_and_completes_agent_run(monkeypatch):
    use_cases = VoiceStreamUseCases()
    fake_run_service = _FakeRunService()
    use_cases._run_service = fake_run_service
    use_cases._session_repo = _FakeSessionRepo()
    monkeypatch.setattr(voice_stream, "process_voice_chat", _fake_voice_chunks)

    request = VoiceChatRequest(
        session_id="voice-session-1",
        system_prompt="你是面试官",
        history=[],
        message="我的回答",
        api_config={"mimo": {"api_key": "x"}},
        audio_id="audio-1",
    )

    generator = await use_cases.stream_voice_chat(request=request, user_id="user-1")
    chunks = [chunk async for chunk in generator]

    assert fake_run_service.created[0]["task_type"] == TASK_TYPE_VOICE_INTERVIEW_TURN
    assert fake_run_service.created[0]["session_id"] == "voice-session-1"
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
    use_cases._session_repo = _FakeSessionRepo()
    monkeypatch.setattr(voice_stream, "process_voice_chat", _cancelled_voice_chunks)

    request = VoiceChatRequest(
        session_id="voice-session-1",
        system_prompt="你是面试官",
        history=[],
        message="我的回答",
        api_config={"mimo": {"api_key": "x"}},
    )

    generator = await use_cases.stream_voice_chat(request=request, user_id="user-1")
    await generator.__anext__()
    with pytest.raises(asyncio.CancelledError):
        await generator.athrow(asyncio.CancelledError())

    assert fake_run_service.failed == [("voice-run-1", "client_disconnected")]
    assert fake_run_service.succeeded == []


class _ExistingVoiceRunService(_FakeRunService):
    async def create_or_get(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="voice-run-1", status="running"), False


@pytest.mark.asyncio
async def test_duplicate_voice_stream_does_not_start_second_media_pipeline(monkeypatch):
    use_cases = VoiceStreamUseCases()
    fake_run_service = _ExistingVoiceRunService()
    use_cases._run_service = fake_run_service
    use_cases._session_repo = _FakeSessionRepo()

    async def unexpected_voice_pipeline(**_kwargs):
        raise AssertionError("duplicate request must not start ASR/TTS")
        yield ""  # pragma: no cover

    monkeypatch.setattr(voice_stream, "process_voice_chat", unexpected_voice_pipeline)
    request = VoiceChatRequest(
        session_id="voice-session-1",
        system_prompt="你是面试官",
        history=[],
        message="我的回答",
        api_config={"mimo": {"api_key": "x"}},
        audio_id="audio-1",
    )

    with pytest.raises(voice_stream.VoiceStreamUseCaseError) as exc_info:
        await use_cases.stream_voice_chat(request=request, user_id="user-1")

    assert exc_info.value.message == "同一面试请求正在执行，请等待当前回复完成"
    assert len(fake_run_service.created) == 1
    assert fake_run_service.stages == []


async def _partially_failed_voice_chunks(**_kwargs):
    yield 'data: {"type":"text","content":"部分输出"}\n\n'
    yield 'data: {"type":"error","content":"authorization: bearer private-token"}\n\n'


@pytest.mark.asyncio
async def test_voice_partial_error_frame_marks_run_failed_with_redaction(monkeypatch):
    use_cases = VoiceStreamUseCases()
    fake_run_service = _FakeRunService()
    use_cases._run_service = fake_run_service
    use_cases._session_repo = _FakeSessionRepo()
    monkeypatch.setattr(voice_stream, "process_voice_chat", _partially_failed_voice_chunks)

    request = VoiceChatRequest(
        session_id="voice-session-1",
        system_prompt="你是面试官",
        history=[],
        message="我的回答",
        api_config={"mimo": {"api_key": "x"}},
        audio_id="audio-1",
    )
    generator = await use_cases.stream_voice_chat(request=request, user_id="user-1")
    chunks = [chunk async for chunk in generator]

    assert fake_run_service.succeeded == []
    assert len(fake_run_service.failed) == 1
    assert "private-token" not in fake_run_service.failed[0][1]
    assert "REDACTED" in fake_run_service.failed[0][1]
    run_events = _agent_run_events(chunks)
    assert [event["type"] for event in run_events] == ["run.started", "run.failed"]
    assert any('"type":"text"' in chunk for chunk in chunks)
