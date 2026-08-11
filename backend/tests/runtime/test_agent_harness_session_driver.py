"""SessionDriver 的 AgentRun lifecycle 契约。"""

import asyncio
from types import SimpleNamespace

import pytest

from ai.runtime.harness.contracts import SessionExecution
from ai.runtime.harness.drivers.session import SessionDriver, SessionDriverConflict


class _FakeRunService:
    def __init__(self, *, created: bool = True, status: str = "running") -> None:
        self.created = created
        self.run = SimpleNamespace(id="session-run-1", status=status)
        self.calls: list[tuple] = []
        self.cancel_requested = False

    async def create_inline_or_get(self, **kwargs):
        self.calls.append(("create_inline_or_get", kwargs))
        return self.run, self.created

    async def mark_stage(self, run_id: str, stage: str) -> None:
        self.calls.append(("stage", run_id, stage))

    async def succeed(self, run_id: str, result: dict) -> None:
        self.calls.append(("succeed", run_id, result))

    async def fail(self, run_id: str, message: str) -> None:
        self.calls.append(("fail", run_id, message))

    async def is_cancel_requested(self, _run_id: str) -> bool:
        return self.cancel_requested

    async def mark_cancelled(self, run_id: str, message: str = "任务已取消") -> None:
        self.calls.append(("cancelled", run_id, message))


class _Lease:
    def __init__(self) -> None:
        self.released = False

    async def release(self) -> None:
        self.released = True


async def _acquire(lease: _Lease) -> _Lease:
    return lease


def _execution(
    *,
    result: dict | None = None,
    error: BaseException | None = None,
    calls: list[tuple] | None = None,
) -> SessionExecution:
    calls = calls if calls is not None else []

    async def bind_run(run_id: str) -> None:
        calls.append(("bind", run_id))

    async def fail_session(message: str) -> None:
        calls.append(("session_failed", message))

    async def cancel_session(message: str) -> None:
        calls.append(("session_cancelled", message))

    async def run(run_id: str, mark_stage) -> dict:
        calls.append(("run", run_id))
        await mark_stage("draft_optimization")
        if error is not None:
            raise error
        return result or {"resume_id": 7, "title": "新简历", "content": "# 新简历"}

    return SessionExecution(
        bind_run=bind_run,
        run=run,
        result=lambda value: {
            "generated_resume_id": value.get("resume_id"),
            "generated_resume_title": value.get("title"),
        },
        fail_session=fail_session,
        cancel_session=cancel_session,
    )


@pytest.mark.asyncio
async def test_session_driver_binds_once_and_succeeds() -> None:
    service = _FakeRunService()
    calls: list[tuple] = []
    driver = SessionDriver(service=service)

    result = await driver.start(
        task_type="resume_generation",
        payload={"generation_session_id": "session-1", "answer_count": 2},
        user_id="user-1",
        session_id="session-1",
        idempotency_key="resume:session-1:answers:abc",
        initial_stage="draft_generation",
        execution=_execution(calls=calls),
    )

    assert result["resume_id"] == 7
    assert calls == [("bind", "session-run-1"), ("run", "session-run-1")]
    assert ("stage", "session-run-1", "draft_optimization") in service.calls
    assert (
        "succeed",
        "session-run-1",
        {"generated_resume_id": 7, "generated_resume_title": "新简历"},
    ) in service.calls
    assert not [call for call in service.calls if call[0] == "fail"]


@pytest.mark.asyncio
async def test_session_driver_rejects_existing_run_without_second_execution() -> None:
    service = _FakeRunService(created=False)
    calls: list[tuple] = []
    driver = SessionDriver(service=service)

    with pytest.raises(SessionDriverConflict, match="正在执行"):
        await driver.start(
            task_type="resume_generation",
            payload={"generation_session_id": "session-1"},
            user_id="user-1",
            session_id="session-1",
            idempotency_key="resume:session-1:answers:abc",
            initial_stage="draft_generation",
            execution=_execution(calls=calls),
        )

    assert calls == []
    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_session_driver_sanitizes_failure_and_releases_gate() -> None:
    service = _FakeRunService()
    lease = _Lease()
    calls: list[tuple] = []
    driver = SessionDriver(service=service, gate_acquire=lambda: _acquire(lease))

    with pytest.raises(RuntimeError):
        await driver.start(
            task_type="resume_generation",
            payload={"generation_session_id": "session-1"},
            user_id="user-1",
            session_id="session-1",
            idempotency_key="resume:session-1:answers:broken",
            initial_stage="draft_generation",
            execution=_execution(
                error=RuntimeError(
                    "authorization=bearer secret-value answers=private answer "
                    "resume_content=private resume"
                ),
                calls=calls,
            ),
            requires_global_gate=True,
        )

    failure = next(call for call in service.calls if call[0] == "fail")
    assert "secret-value" not in failure[2]
    assert "private answer" not in failure[2]
    assert "private resume" not in failure[2]
    assert "REDACTED" in failure[2]
    assert calls[-1][0] == "session_failed"
    assert lease.released is True


@pytest.mark.asyncio
async def test_session_driver_converges_cancellation_without_success() -> None:
    service = _FakeRunService()
    service.cancel_requested = True
    calls: list[tuple] = []
    driver = SessionDriver(service=service)

    with pytest.raises(SessionDriverConflict, match="已取消"):
        await driver.start(
            task_type="resume_generation",
            payload={"generation_session_id": "session-1"},
            user_id="user-1",
            session_id="session-1",
            idempotency_key="resume:session-1:answers:cancelled",
            initial_stage="draft_generation",
            execution=_execution(calls=calls),
        )

    assert ("cancelled", "session-run-1", "任务已取消") in service.calls
    assert ("session_cancelled", "任务已取消") in calls
    assert not [call for call in service.calls if call[0] == "succeed"]


@pytest.mark.asyncio
async def test_session_driver_propagates_task_cancellation_and_releases_gate() -> None:
    service = _FakeRunService()
    lease = _Lease()
    calls: list[tuple] = []
    started = asyncio.Event()

    async def bind_run(run_id: str) -> None:
        calls.append(("bind", run_id))

    async def fail_session(message: str) -> None:
        calls.append(("session_failed", message))

    async def cancel_session(message: str) -> None:
        calls.append(("session_cancelled", message))

    async def run(_run_id: str, _mark_stage) -> dict:
        started.set()
        await asyncio.Future()
        return {}

    driver = SessionDriver(service=service, gate_acquire=lambda: _acquire(lease))
    task = asyncio.create_task(
        driver.start(
            task_type="resume_generation",
            payload={"generation_session_id": "session-1"},
            user_id="user-1",
            session_id="session-1",
            idempotency_key="resume:session-1:answers:disconnect",
            initial_stage="draft_generation",
            execution=SessionExecution(
                bind_run=bind_run,
                run=run,
                result=lambda value: value,
                fail_session=fail_session,
                cancel_session=cancel_session,
            ),
            requires_global_gate=True,
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ("cancelled", "session-run-1", "任务已取消") in service.calls
    assert ("session_cancelled", "任务已取消") in calls
    assert lease.released is True
