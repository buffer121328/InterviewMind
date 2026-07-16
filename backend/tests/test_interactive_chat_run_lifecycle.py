"""文字面试流式生成接入持久化 AgentRun。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.application.interview import stream as chat_stream
from app.application.interview.checkpoints import interview_turn_checkpoint_thread_id
from app.application.interview.stream import ChatStreamUseCases
from app.schemas.schemas import ChatRequest
from app.services.agent_runs.service import TASK_TYPE_INTERVIEW_TURN, get_task_definition


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


class _FakeSessionRepo:
    def __init__(self):
        self.added = []
        self.updated = []
        self.session = SimpleNamespace(
            messages=[SimpleNamespace(role="assistant", content="上一题", question_index=0)],
            metadata=SimpleNamespace(round_index=1, round_type="tech_initial"),
        )

    async def get_session(self, *_args, **_kwargs):
        return self.session

    async def get_interview_plan(self, *_args, **_kwargs):
        return [{"content": "上一题"}]

    async def add_message(self, **kwargs):
        self.added.append(kwargs)

    async def update_session(self, **kwargs):
        self.updated.append(kwargs)


class _FakeRunService:
    def __init__(self):
        self.created = []
        self.stages = []
        self.succeeded = []
        self.failed = []

    async def create_or_get(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="run-1"), True

    async def claim(self, run_id):
        assert run_id == "run-1"
        return SimpleNamespace(id=run_id), {}

    async def mark_stage(self, run_id, stage):
        self.stages.append((run_id, stage))

    async def succeed(self, run_id, result):
        self.succeeded.append((run_id, result))

    async def fail(self, run_id, message):
        self.failed.append((run_id, message))


class _FakeLease:
    def __init__(self):
        self.released = False

    async def release(self):
        self.released = True


class _FakeGate:
    def __init__(self, lease):
        self.lease = lease

    async def acquire(self):
        return self.lease


class _FakeGraph:
    def __init__(self):
        self.config = None

    async def astream_events(self, *_args, **kwargs):
        self.config = kwargs.get("config")
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "responder"},
            "data": {"chunk": SimpleNamespace(content="新问题")},
        }
        yield {
            "event": "on_chain_end",
            "data": {"output": {"current_question_index": 1, "question_count": 1, "max_questions": 5}},
        }


def test_interview_turn_checkpoint_thread_id_uses_persisted_run_id():
    assert interview_turn_checkpoint_thread_id("session-1", "run-1") == "interview:session-1:run:run-1"


def test_interview_turn_task_definition_is_registered():
    definition = get_task_definition(TASK_TYPE_INTERVIEW_TURN)
    assert definition["title"] == "生成面试追问与反馈"
    assert ("generating_response", "生成反馈与下一题") in definition["steps"]


@pytest.mark.asyncio
async def test_chat_stream_creates_and_completes_agent_run(monkeypatch):
    lease = _FakeLease()
    use_cases = ChatStreamUseCases()
    use_cases._session_repo = _FakeSessionRepo()
    fake_run_service = _FakeRunService()
    use_cases._run_service = fake_run_service

    fake_graph = _FakeGraph()

    async def fake_build_interview_graph(_mode):
        return fake_graph

    async def fake_get_memory_context(**_kwargs):
        return "", []

    monkeypatch.setattr(chat_stream, "build_interview_graph", fake_build_interview_graph)
    monkeypatch.setattr(chat_stream, "get_memory_context", fake_get_memory_context)
    monkeypatch.setattr(chat_stream, "get_run_gate", lambda: _FakeGate(lease))

    request = ChatRequest(
        thread_id="thread-1",
        message="我的回答",
        mode="mock",
        resume_context="简历",
        job_description="JD",
        max_questions=5,
    )

    generator = await use_cases.stream_chat(request=request, user_id="user-1")
    chunks = [chunk async for chunk in generator]

    assert fake_run_service.created[0]["task_type"] == TASK_TYPE_INTERVIEW_TURN
    assert fake_run_service.created[0]["payload"]["thread_id"] == "thread-1"
    assert fake_graph.config == {"configurable": {"thread_id": "interview:thread-1:run:run-1"}}
    assert fake_run_service.stages == [
        ("run-1", "loading_session"),
        ("run-1", "saving_answer"),
        ("run-1", "generating_response"),
        ("run-1", "saving_response"),
    ]
    assert fake_run_service.succeeded == [("run-1", {"thread_id": "thread-1", "question_index": 1})]
    assert fake_run_service.failed == []
    assert lease.released is True
    run_events = _agent_run_events(chunks)
    assert {event["type"] for event in run_events} >= {"run.started", "run.completed"}
    assert all(event["run_id"] == "run-1" for event in run_events)


class _CancelledGraph:
    async def astream_events(self, *_args, **_kwargs):
        raise asyncio.CancelledError()
        yield {}  # pragma: no cover


@pytest.mark.asyncio
async def test_chat_stream_disconnect_marks_run_failed_not_cancelled(monkeypatch):
    lease = _FakeLease()
    use_cases = ChatStreamUseCases()
    use_cases._session_repo = _FakeSessionRepo()
    fake_run_service = _FakeRunService()
    use_cases._run_service = fake_run_service

    async def fake_build_interview_graph(_mode):
        return _CancelledGraph()

    async def fake_get_memory_context(**_kwargs):
        return "", []

    monkeypatch.setattr(chat_stream, "build_interview_graph", fake_build_interview_graph)
    monkeypatch.setattr(chat_stream, "get_memory_context", fake_get_memory_context)
    monkeypatch.setattr(chat_stream, "get_run_gate", lambda: _FakeGate(lease))

    request = ChatRequest(
        thread_id="thread-1",
        message="我的回答",
        mode="mock",
        resume_context="简历",
        job_description="JD",
        max_questions=5,
    )

    generator = await use_cases.stream_chat(request=request, user_id="user-1")
    with pytest.raises(asyncio.CancelledError):
        [chunk async for chunk in generator]

    assert fake_run_service.failed == [("run-1", "client_disconnected")]
    assert fake_run_service.succeeded == []
    assert lease.released is True
