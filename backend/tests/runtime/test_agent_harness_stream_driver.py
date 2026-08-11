"""StreamDriver 的 AgentRun lifecycle 契约。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from ai.runtime.harness.contracts import StreamExecution
from ai.runtime.harness.drivers.stream import StreamDriver, StreamDriverConflict


class _FakeRunService:
    def __init__(self, *, created: bool = True, status: str = "queued") -> None:
        self.created = created
        self.run = SimpleNamespace(id="stream-run-1", status=status)
        self.calls: list[tuple] = []

    async def create_or_get(self, **kwargs):
        self.calls.append(("create_or_get", kwargs))
        return self.run, self.created

    async def claim(self, run_id: str):
        self.calls.append(("claim", run_id))
        return SimpleNamespace(id=run_id), {}

    async def mark_stage(self, run_id: str, stage: str):
        self.calls.append(("stage", run_id, stage))

    async def succeed(self, run_id: str, result: dict):
        self.calls.append(("succeed", run_id, result))

    async def fail(self, run_id: str, message: str):
        self.calls.append(("fail", run_id, message))


class _Lease:
    def __init__(self) -> None:
        self.released = False

    async def release(self) -> None:
        self.released = True


async def _chunks(*values: str):
    for value in values:
        yield value


def _encode_run_event(envelope: dict) -> str:
    return f"data: {json.dumps({'type': 'agent_run_event', 'content': envelope})}\n\n"


def _encode_error(message: str) -> str:
    return f"data: {json.dumps({'type': 'error', 'content': message})}\n\n"


def _detect_error(chunk: str) -> str | None:
    if not chunk.startswith("data: "):
        return None
    event = json.loads(chunk.removeprefix("data: ").strip())
    if event.get("type") != "error":
        return None
    return str(event.get("content") or event.get("message") or "stream failed")


async def _execution(*values: str, result: dict | None = None) -> StreamExecution:
    return StreamExecution(
        source=_chunks(*values),
        result=lambda: result or {"ok": True},
        encode_run_event=_encode_run_event,
        encode_error=_encode_error,
        detect_error=_detect_error,
    )


@pytest.mark.asyncio
async def test_stream_driver_claims_once_and_succeeds_after_partial_output() -> None:
    service = _FakeRunService()
    driver = StreamDriver(service=service)

    stream = await driver.start(
        task_type="interview_turn",
        payload={"thread_id": "session-1"},
        user_id="user-1",
        session_id="session-1",
        idempotency_key="text:session-1:0:abc",
        initial_stage="loading_session",
        stream_factory=lambda _run_id: _execution(
            'data: {"type":"token","content":"first"}\n\n',
            'data: {"type":"done","content":"[DONE]"}\n\n',
            result={"thread_id": "session-1", "question_index": 1},
        ),
    )
    chunks = [chunk async for chunk in stream]

    assert [call[0] for call in service.calls].count("claim") == 1
    assert ("stage", "stream-run-1", "loading_session") in service.calls
    assert ("succeed", "stream-run-1", {"thread_id": "session-1", "question_index": 1}) in service.calls
    assert not [call for call in service.calls if call[0] == "fail"]
    run_events = [
        json.loads(chunk.removeprefix("data: ").strip())["content"]
        for chunk in chunks
        if '"agent_run_event"' in chunk
    ]
    assert [event["type"] for event in run_events] == ["run.started", "run.completed"]
    assert [event["sequence"] for event in run_events] == [1, 2]
    assert [event["event_id"] for event in run_events] == [
        "inline:stream-run-1:1",
        "inline:stream-run-1:2",
    ]


@pytest.mark.asyncio
async def test_stream_driver_marks_error_frame_failed_after_partial_output() -> None:
    service = _FakeRunService()
    driver = StreamDriver(service=service)

    stream = await driver.start(
        task_type="voice_interview_turn",
        payload={"session_id": "session-1", "has_audio": True},
        user_id="user-1",
        session_id="session-1",
        idempotency_key="voice:session-1:audio-1",
        initial_stage="generating_response",
        stream_factory=lambda _run_id: _execution(
            'data: {"type":"text","content":"partial"}\n\n',
            'data: {"type":"error","content":"api_key=sk-12345678901234567890"}\n\n',
        ),
    )
    chunks = [chunk async for chunk in stream]

    failure = next(call for call in service.calls if call[0] == "fail")
    assert failure[1] == "stream-run-1"
    assert "sk-" not in failure[2]
    assert "REDACTED" in failure[2]
    assert not [call for call in service.calls if call[0] == "succeed"]
    assert any('"type": "error"' in chunk or '"type":"error"' in chunk for chunk in chunks)
    assert any('"run.failed"' in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_stream_driver_sanitizes_exception_and_releases_gate() -> None:
    service = _FakeRunService()
    lease = _Lease()

    async def broken_execution(_run_id: str) -> StreamExecution:
        raise RuntimeError(
            "authorization: bearer secret-value transcript=private spoken answer"
        )

    driver = StreamDriver(service=service, gate_acquire=lambda: _acquire(lease))
    stream = await driver.start(
        task_type="interview_turn",
        payload={"thread_id": "session-1"},
        user_id="user-1",
        session_id="session-1",
        idempotency_key="text:session-1:0:broken",
        initial_stage="loading_session",
        stream_factory=broken_execution,
        requires_global_gate=True,
    )
    chunks = [chunk async for chunk in stream]

    failure = next(call for call in service.calls if call[0] == "fail")
    assert "secret-value" not in failure[2]
    assert "private spoken answer" not in failure[2]
    assert "REDACTED" in failure[2]
    assert lease.released is True
    assert any('"type": "error"' in chunk or '"type":"error"' in chunk for chunk in chunks)


async def _acquire(lease: _Lease) -> _Lease:
    return lease


@pytest.mark.asyncio
async def test_stream_driver_disconnect_marks_client_disconnected_and_releases_gate() -> None:
    service = _FakeRunService()
    lease = _Lease()
    started = asyncio.Event()

    async def waiting_source():
        started.set()
        await asyncio.Future()
        yield ""  # pragma: no cover

    async def waiting_execution(_run_id: str) -> StreamExecution:
        return StreamExecution(
            source=waiting_source(),
            result=lambda: {"ok": True},
            encode_run_event=_encode_run_event,
            encode_error=_encode_error,
            detect_error=_detect_error,
        )

    driver = StreamDriver(service=service, gate_acquire=lambda: _acquire(lease))
    stream = await driver.start(
        task_type="interview_turn",
        payload={"thread_id": "session-1"},
        user_id="user-1",
        session_id="session-1",
        idempotency_key="text:session-1:0:disconnect",
        initial_stage="loading_session",
        stream_factory=waiting_execution,
        requires_global_gate=True,
    )
    await stream.__anext__()
    with pytest.raises(asyncio.CancelledError):
        await stream.athrow(asyncio.CancelledError())

    assert started.is_set() is False
    assert ("fail", "stream-run-1", "client_disconnected") in service.calls
    assert lease.released is True
    assert not [call for call in service.calls if call[0] == "succeed"]


@pytest.mark.asyncio
async def test_stream_driver_rejects_existing_run_without_second_claim() -> None:
    service = _FakeRunService(created=False, status="running")
    driver = StreamDriver(service=service)

    with pytest.raises(StreamDriverConflict, match="正在执行"):
        await driver.start(
            task_type="interview_turn",
            payload={"thread_id": "session-1"},
            user_id="user-1",
            session_id="session-1",
            idempotency_key="text:session-1:0:duplicate",
            initial_stage="loading_session",
            stream_factory=lambda _run_id: _execution(),
        )

    assert not [call for call in service.calls if call[0] == "claim"]


class _CancellationRequestedService(_FakeRunService):
    async def is_cancel_requested(self, _run_id: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_stream_driver_converges_cancel_request_to_cancelled_terminal() -> None:
    service = _CancellationRequestedService()
    driver = StreamDriver(service=service)

    stream = await driver.start(
        task_type="interview_turn",
        payload={"thread_id": "session-1"},
        user_id="user-1",
        session_id="session-1",
        idempotency_key="text:session-1:0:cancelled",
        initial_stage="loading_session",
        stream_factory=lambda _run_id: _execution(
            'data: {"type":"token","content":"must-not-send"}\n\n',
        ),
    )
    chunks = [chunk async for chunk in stream]

    assert ("fail", "stream-run-1", "任务已取消") in service.calls
    assert not [call for call in service.calls if call[0] == "succeed"]
    run_events = [
        json.loads(chunk.removeprefix("data: ").strip())["content"]
        for chunk in chunks
        if '"agent_run_event"' in chunk
    ]
    assert [event["type"] for event in run_events] == ["run.started", "run.cancelled"]
    assert not any("must-not-send" in chunk for chunk in chunks)
