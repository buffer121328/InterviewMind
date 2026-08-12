"""文字面试流式生成接入持久化 AgentRun。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from ai.runtime.agent_runs.service import get_task_definition
from ai.workflows.interview.chat import stream as chat_stream
from ai.workflows.interview.sessions.checkpoints import interview_turn_checkpoint_thread_id
from ai.workflows.interview.chat.stream import ChatStreamUseCases
from app.domain.agent_runs import TASK_TYPE_INTERVIEW_TURN
from app.schemas.schemas import ChatRequest


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
            metadata=SimpleNamespace(),
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
        self.inputs = None

    async def astream_events(self, *args, **kwargs):
        self.config = kwargs.get("config")
        self.inputs = args[0]
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "responder"},
            "data": {"chunk": SimpleNamespace(content='{"action":"follow_up"}')},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "responder"},
            "data": {"output": {
                "messages": [SimpleNamespace(type="ai", content="好的，进入第二题。")],
                "current_question_index": 1,
                "question_count": 1,
                "max_questions": 5,
            }},
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
    assert fake_run_service.created[0]["session_id"] == "thread-1"
    assert fake_run_service.created[0]["payload"]["thread_id"] == "thread-1"
    assert fake_graph.config["configurable"] == {"thread_id": "interview:thread-1:run:run-1"}
    assert fake_graph.config["run_name"] == "interview-turn"
    assert fake_graph.config["metadata"] == {
        "agent_type": "interview",
        "user_id": "user-1",
        "session_id": "thread-1",
        "run_id": "run-1",
    }
    assert fake_graph.inputs["round_index"] == 1
    assert fake_graph.inputs["round_type"] is None
    assert fake_graph.inputs["max_questions"] == 5
    assert fake_run_service.stages == [
        ("run-1", "loading_session"),
        ("run-1", "saving_answer"),
        ("run-1", "generating_response"),
        ("run-1", "saving_response"),
    ]
    assert fake_run_service.succeeded == [("run-1", {"thread_id": "thread-1", "question_index": 1})]
    assert fake_run_service.failed == []
    assert use_cases._session_repo.added[-1]["content"] == "好的，进入第二题。"
    assert '{"action"' not in use_cases._session_repo.added[-1]["content"]
    assert lease.released is True
    run_events = _agent_run_events(chunks)
    assert {event["type"] for event in run_events} >= {"run.started", "run.completed"}
    assert all(event["run_id"] == "run-1" for event in run_events)
    assert [event["sequence"] for event in run_events] == list(range(1, len(run_events) + 1))
    assert [event["event_id"] for event in run_events] == [f"inline:run-1:{index}" for index in range(1, len(run_events) + 1)]


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


class _ExistingChatRunService(_FakeRunService):
    async def create_or_get(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="run-1", status="running"), False


@pytest.mark.asyncio
async def test_duplicate_chat_stream_does_not_build_or_claim_a_second_graph(monkeypatch):
    use_cases = ChatStreamUseCases()
    use_cases._session_repo = _FakeSessionRepo()
    fake_run_service = _ExistingChatRunService()
    use_cases._run_service = fake_run_service

    async def unexpected_graph(_mode):
        raise AssertionError("duplicate request must not build the graph")

    async def fake_get_memory_context(**_kwargs):
        return "", []

    monkeypatch.setattr(chat_stream, "build_interview_graph", unexpected_graph)
    monkeypatch.setattr(chat_stream, "get_memory_context", fake_get_memory_context)
    monkeypatch.setattr(chat_stream, "get_run_gate", lambda: _FakeGate(_FakeLease()))

    request = ChatRequest(
        thread_id="thread-1",
        message="我的回答",
        mode="mock",
        resume_context="简历",
        job_description="JD",
        max_questions=5,
    )

    with pytest.raises(chat_stream.ChatStreamConflict) as exc_info:
        await use_cases.stream_chat(request=request, user_id="user-1")

    assert exc_info.value.message == "同一面试请求正在执行，请等待当前回复完成"
    assert len(fake_run_service.created) == 1
    assert fake_run_service.stages == []


class _PartialFailureGraph:
    async def astream_events(self, *_args, **_kwargs):
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "responder"},
            "data": {"output": {
                "messages": [SimpleNamespace(type="ai", content="已收到你的回答")],
                "current_question_index": 0,
            }},
        }
        raise RuntimeError("api_key=sk-12345678901234567890")


@pytest.mark.asyncio
async def test_chat_stream_partial_failure_has_one_safe_failed_terminal(monkeypatch):
    lease = _FakeLease()
    use_cases = ChatStreamUseCases()
    use_cases._session_repo = _FakeSessionRepo()
    fake_run_service = _FakeRunService()
    use_cases._run_service = fake_run_service

    async def fake_build_interview_graph(_mode):
        return _PartialFailureGraph()

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

    assert fake_run_service.succeeded == []
    assert len(fake_run_service.failed) == 1
    assert "sk-" not in fake_run_service.failed[0][1]
    assert "REDACTED" in fake_run_service.failed[0][1]
    run_events = _agent_run_events(chunks)
    assert [event["type"] for event in run_events][-1] == "run.failed"
    assert "run.completed" not in {event["type"] for event in run_events}
    assert any('"type":"token"' in chunk for chunk in chunks)
    assert lease.released is True
