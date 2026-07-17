"""单用户任务队列的无外部依赖单元测试。"""

from datetime import datetime
import json

import pytest
from cryptography.fernet import Fernet

from app.models.agent_run import AgentRunModel
from app.schemas.schemas import InterviewStartRequest
from app.services.agent_runs.crypto import (
    TaskPayloadConfigurationError,
    decrypt_payload,
    encrypt_payload,
)
from app.services.agent_runs.service import (
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_RESUME_OPTIMIZE,
    build_interview_start_plan,
    build_task_plan,
    serialize_run,
)
from app.services.runtime_gate import LocalRunGate


def test_task_payload_is_encrypted_and_round_trips(monkeypatch):
    monkeypatch.setenv("TASK_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    payload = {"api_config": {"smart": {"api_key": "test-key"}}, "resume_context": "private resume"}

    encrypted = encrypt_payload(payload)

    assert "test-key" not in encrypted
    assert "private resume" not in encrypted
    assert decrypt_payload(encrypted) == payload


def test_queue_rejects_payload_when_encryption_key_missing(monkeypatch):
    monkeypatch.delenv("TASK_PAYLOAD_ENCRYPTION_KEY", raising=False)

    with pytest.raises(TaskPayloadConfigurationError):
        encrypt_payload({"resume_context": "private resume"})


@pytest.mark.asyncio
async def test_local_run_gate_allows_only_one_active_task():
    gate = LocalRunGate()
    first = await gate.acquire()
    second = await gate.acquire()

    assert first is not None
    assert second is None

    await first.release()
    assert await gate.acquire() is not None


def test_sync_mode_uses_local_gate_even_with_redis_url(monkeypatch):
    from app.services import runtime_gate

    monkeypatch.setenv("TASK_QUEUE_ENABLED", "false")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    assert isinstance(runtime_gate.get_run_gate(), LocalRunGate)


def test_serialized_run_excludes_encrypted_payload():
    now = datetime.now()
    run = AgentRunModel(
        id="run-1", user_id="user-1", task_type="interview_start", status="queued", stage="queued",
        idempotency_key="turn-1", payload_encrypted="never-expose", result=None, error_message=None,
        trace_id="trace-1", model_provider="openai", model_name="gpt-5", model_member="smart",
        request_latency_ms=123, input_tokens=456, output_tokens=789, fallback_count=2, model_error_type="RateLimitError",
        attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
    )

    public = serialize_run(run)

    assert public["run_id"] == "run-1"
    assert "payload_encrypted" not in public
    assert public["plan"][0] == {
        "id": "queued",
        "title": "等待执行资源",
        "status": "running",
    }
    assert public["max_attempts"] == 3
    assert public["trace_id"] == "trace-1"
    assert public["model_provider"] == "openai"
    assert public["input_tokens"] == 456
    assert public["fallback_count"] == 2
    assert public["can_retry"] is False


def test_failed_run_plan_marks_last_business_stage():
    plan = build_interview_start_plan("loading_context", "failed")

    assert [step["status"] for step in plan] == ["completed", "failed", "pending"]


def test_generic_task_plans_are_task_specific():
    resume_plan = build_task_plan(TASK_TYPE_RESUME_OPTIMIZE, "optimizing", "running")
    report_plan = build_task_plan(TASK_TYPE_INTERVIEW_REPORT, "generating_weakness", "running")

    assert [step["id"] for step in resume_plan] == ["queued", "preparing", "optimizing", "saving_result"]
    assert resume_plan[2]["status"] == "running"
    assert report_plan[3]["status"] == "running"




def test_serialized_run_includes_observability_fields_when_present():
    now = datetime.now()
    run = AgentRunModel(
        id="run-obs", user_id="user-1", task_type="interview_start", status="running", stage="loading_context",
        idempotency_key="turn-obs", payload_encrypted="encrypted", result=None, error_message=None,
        trace_id="trace-obs", model_provider="anthropic", model_name="claude", model_member="fallback",
        request_latency_ms=88, input_tokens=10, output_tokens=20, fallback_count=1,
        fallback_path=[{"model_name": "claude", "status": "completed"}], estimated_cost_usd=0.0012,
        model_error_type="TimeoutError",
        attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=None,
    )

    public = serialize_run(run)

    assert public["trace_id"] == "trace-obs"
    assert public["model_provider"] == "anthropic"
    assert public["model_name"] == "claude"
    assert public["request_latency_ms"] == 88
    assert public["fallback_path"] == [{"model_name": "claude", "status": "completed"}]
    assert public["estimated_cost_usd"] == 0.0012
    assert public["model_error_type"] == "TimeoutError"


@pytest.mark.asyncio
async def test_queued_start_dispatches_only_run_id(monkeypatch):
    from app.api import agent_runs

    now = datetime.now()
    run = AgentRunModel(
        id="run-1", user_id="user-1", task_type="interview_start", status="queued", stage="queued",
        idempotency_key="turn-1", payload_encrypted="encrypted", result=None, error_message=None,
        attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
    )
    dispatched: list[str] = []
    dispatch_calls: list[int] = []

    async def create_or_get(**_kwargs):
        return run, True

    def enqueue(run_id: str) -> None:
        dispatched.append(run_id)

    async def dispatch_pending_outbox(*, limit, enqueue_fn):
        dispatch_calls.append(limit)
        enqueue_fn(run.id)
        return 1, 0

    monkeypatch.setattr(agent_runs, "task_queue_enabled", lambda: True)
    monkeypatch.setattr(agent_runs.service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_runs, "enqueue_interview_start", enqueue)
    monkeypatch.setattr(agent_runs, "dispatch_pending_outbox", dispatch_pending_outbox)

    response = await agent_runs.create_interview_start_run(
        InterviewStartRequest(thread_id="turn-1", mode="mock", resume_context="private resume"),
        user_id="user-1",
        idempotency_key="turn-1",
    )

    assert response.status_code == 202
    assert dispatched == ["run-1"]
    assert dispatch_calls == [50]
    assert "private resume" not in response.body.decode()
    assert json.loads(response.body)["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_queued_start_keeps_run_retryable_when_outbox_dispatch_fails(monkeypatch):
    from app.api import agent_runs

    now = datetime.now()
    run = AgentRunModel(
        id="run-1", user_id="user-1", task_type="interview_start", status="queued", stage="queued",
        idempotency_key="turn-1", payload_encrypted="encrypted", result=None, error_message=None,
        attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
    )
    failed: list[tuple[str, str]] = []

    async def create_or_get(**_kwargs):
        return run, True

    async def fail(run_id, message):
        failed.append((run_id, message))

    async def dispatch_pending_outbox(*, limit, enqueue_fn):
        return 0, 1

    monkeypatch.setattr(agent_runs, "task_queue_enabled", lambda: True)
    monkeypatch.setattr(agent_runs.service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_runs.service, "fail", fail)
    monkeypatch.setattr(agent_runs, "dispatch_pending_outbox", dispatch_pending_outbox)

    response = await agent_runs.create_interview_start_run(
        InterviewStartRequest(thread_id="turn-1", mode="mock", resume_context="private resume"),
        user_id="user-1",
        idempotency_key="turn-1",
    )

    assert response.status_code == 202
    assert failed == []
    assert json.loads(response.body)["status"] == "queued"


@pytest.mark.asyncio
async def test_existing_queued_run_is_not_dispatched_twice(monkeypatch):
    from app.api import agent_runs

    now = datetime.now()
    run = AgentRunModel(
        id="run-1", user_id="user-1", task_type="interview_start", status="queued", stage="queued",
        idempotency_key="turn-1", payload_encrypted="encrypted", result=None, error_message=None,
        attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
    )
    dispatched: list[str] = []
    dispatch_calls: list[int] = []

    async def create_or_get(**_kwargs):
        return run, False

    async def dispatch_pending_outbox(*, limit, enqueue_fn):
        dispatch_calls.append(limit)
        enqueue_fn(run.id)
        return 1, 0

    monkeypatch.setattr(agent_runs, "task_queue_enabled", lambda: True)
    monkeypatch.setattr(agent_runs.service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_runs, "enqueue_interview_start", dispatched.append)
    monkeypatch.setattr(agent_runs, "dispatch_pending_outbox", dispatch_pending_outbox)

    response = await agent_runs.create_interview_start_run(
        InterviewStartRequest(thread_id="turn-1", mode="mock", resume_context="private resume"),
        user_id="user-1",
        idempotency_key="turn-1",
    )

    assert response.status_code == 202
    assert dispatched == []
    assert dispatch_calls == []


@pytest.mark.asyncio
async def test_redis_run_gate_renews_owned_lock(monkeypatch):
    from app.services import runtime_gate

    class FakeRedis:
        def __init__(self):
            self.calls = []

        async def set(self, *args, **kwargs):
            return True

        async def eval(self, script, *args):
            self.calls.append((script, args))
            return 1

    gate = object.__new__(runtime_gate.RedisRunGate)
    gate._client = FakeRedis()
    gate._ttl = 3

    lease = await gate.acquire()
    assert lease is not None
    await __import__("asyncio").sleep(1.1)
    await lease.release()

    assert any("expire" in script for script, _args in gate._client.calls)


def test_serialized_running_run_can_be_cancelled():
    now = datetime.now()
    run = AgentRunModel(
        id="run-running", user_id="user-1", task_type="interview_start", status="running", stage="loading_context",
        idempotency_key="turn-running", payload_encrypted="encrypted", result=None, error_message=None,
        attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=None,
    )

    public = serialize_run(run)

    assert public["can_cancel"] is True
    assert public["can_retry"] is False


def test_serialized_run_event_has_replay_envelope():
    from app.models.agent_run import AgentRunEventModel
    from app.services.agent_runs.service import serialize_event

    now = datetime.now()
    event = AgentRunEventModel(
        id=7,
        run_id="run-1",
        sequence=3,
        event_type="run.stage.changed",
        stage="optimizing",
        payload={"detail": "working"},
        schema_version=1,
        created_at=now,
    )

    public = serialize_event(event)

    assert public == {
        "event_id": "7",
        "run_id": "run-1",
        "sequence": 3,
        "type": "run.stage.changed",
        "stage": "optimizing",
        "payload": {"detail": "working"},
        "schema_version": 1,
        "timestamp": now.isoformat(),
    }


@pytest.mark.asyncio
async def test_cancel_api_returns_cancel_requested_for_running_run(monkeypatch):
    from app.api import agent_runs

    now = datetime.now()
    run = AgentRunModel(
        id="run-running", user_id="user-1", task_type="interview_start", status="cancel_requested", stage="loading_context",
        idempotency_key="turn-running", payload_encrypted="encrypted", result=None, error_message="正在请求取消当前任务",
        attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=None,
    )

    async def cancel(_run_id, _user_id):
        return run

    monkeypatch.setattr(agent_runs.service, "cancel", cancel)

    response = await agent_runs.cancel_agent_run("run-running", user_id="user-1")

    assert response["status"] == "cancel_requested"
    assert response["can_cancel"] is True


@pytest.mark.asyncio
async def test_recovery_loop_dispatches_recovered_runs(monkeypatch):
    from types import SimpleNamespace
    from app.services.agent_runs import recovery

    dispatch_calls = []

    class FakeService:
        async def recover_all_stale_runs(self, limit=200):
            return [SimpleNamespace(id="run-recovered")]

    async def dispatch_pending_outbox(*, limit):
        dispatch_calls.append(limit)
        return 1, 0

    async def stop_after_first_sleep(_seconds):
        raise __import__("asyncio").CancelledError

    monkeypatch.setattr(recovery, "task_queue_enabled", lambda: True)
    monkeypatch.setattr(recovery, "AgentRunService", FakeService)
    monkeypatch.setattr(recovery, "dispatch_pending_outbox", dispatch_pending_outbox)
    monkeypatch.setattr(recovery.asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(__import__("asyncio").CancelledError):
        await recovery.run_agent_run_recovery_loop()

    assert dispatch_calls == [200]


@pytest.mark.asyncio
async def test_recovery_loop_marks_failed_dispatch_and_continues(monkeypatch):
    from types import SimpleNamespace
    from app.services.agent_runs import recovery

    dispatch_calls: list[int] = []

    class FakeService:
        async def recover_all_stale_runs(self, limit=200):
            return [SimpleNamespace(id="run-bad"), SimpleNamespace(id="run-ok")]

        async def fail(self, *_args):
            raise AssertionError("Outbox 投递失败不应直接 fail run")

    async def dispatch_pending_outbox(*, limit):
        dispatch_calls.append(limit)
        return 1, 1

    async def stop_after_first_sleep(_seconds):
        raise __import__("asyncio").CancelledError

    monkeypatch.setattr(recovery, "task_queue_enabled", lambda: True)
    monkeypatch.setattr(recovery, "AgentRunService", FakeService)
    monkeypatch.setattr(recovery, "dispatch_pending_outbox", dispatch_pending_outbox)
    monkeypatch.setattr(recovery.asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(__import__("asyncio").CancelledError):
        await recovery.run_agent_run_recovery_loop()

    assert dispatch_calls == [200]


@pytest.mark.asyncio
async def test_succeed_turns_cancel_requested_run_into_cancelled(monkeypatch):
    from app.services.agent_runs import service as service_module

    now = datetime.now()
    run = AgentRunModel(
        id="run-cancel", user_id="user-1", task_type="interview_start", status="cancel_requested", stage="loading_context",
        idempotency_key="turn-cancel", payload_encrypted="encrypted", result=None, error_message="正在请求取消当前任务",
        attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=None,
    )
    appended: list[tuple[str, dict | None]] = []

    class FakeSession:
        async def get(self, _model, run_id, with_for_update=False):
            assert run_id == "run-cancel"
            assert with_for_update is True
            return run

        async def commit(self):
            return None

        async def rollback(self):
            raise AssertionError("不应回滚成功路径")

        async def close(self):
            return None

    async def append_event(self, _session, _run, event_type, payload=None):
        appended.append((event_type, payload))

    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())
    monkeypatch.setattr(service_module.AgentRunService, "_append_event", append_event)

    await service_module.AgentRunService().succeed("run-cancel", {"success": True})

    assert run.status == "cancelled"
    assert run.stage == "cancelled"
    assert run.result is None
    assert run.error_message == "任务已取消"
    assert run.finished_at is not None
    assert appended == [("run.cancelled", {"reason": "cancel_won_race"})]


@pytest.mark.asyncio
async def test_succeed_with_result_writer_uses_same_uow_session(monkeypatch):
    from app.services.agent_runs import service as service_module

    now = datetime.now()
    run = AgentRunModel(
        id="run-ok", user_id="user-1", task_type="interview_start", status="running", stage="loading_context",
        idempotency_key="turn-ok", payload_encrypted="encrypted", result=None, error_message=None,
        attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=None,
    )
    appended: list[tuple[str, dict | None]] = []
    writer_sessions: list[object] = []
    commits: list[str] = []

    class FakeSession:
        async def get(self, _model, run_id, with_for_update=False):
            assert run_id == "run-ok"
            assert with_for_update is True
            return run

        async def commit(self):
            commits.append("commit")

        async def rollback(self):
            raise AssertionError("不应回滚成功路径")

        async def close(self):
            return None

    async def append_event(self, _session, _run, event_type, payload=None):
        appended.append((event_type, payload))

    async def write_business_result(session):
        writer_sessions.append(session)
        return {"success": True, "result_id": 7}

    fake_session = FakeSession()
    monkeypatch.setattr(service_module, "async_session", lambda: fake_session)
    monkeypatch.setattr(service_module.AgentRunService, "_append_event", append_event)

    await service_module.AgentRunService().succeed_with_result_writer("run-ok", write_business_result)

    assert writer_sessions == [fake_session]
    assert commits == ["commit"]
    assert run.status == "succeeded"
    assert run.stage == "succeeded"
    assert run.result == {"success": True, "result_id": 7}
    assert run.finished_at is not None
    assert appended == [("run.completed", None)]


@pytest.mark.asyncio
async def test_record_observation_persists_summary_and_model_events(monkeypatch):
    from app.services.agent_runs import service as service_module

    now = datetime.now()
    run = AgentRunModel(
        id="run-obs", user_id="user-1", task_type="voice_interview_turn", status="running", stage="generating_response",
        idempotency_key="voice-turn", payload_encrypted="encrypted", result=None, error_message=None,
        attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=None,
    )
    appended: list[tuple[str, dict | None]] = []
    commits: list[str] = []

    class FakeSession:
        async def get(self, _model, run_id, with_for_update=False):
            assert run_id == "run-obs"
            assert with_for_update is True
            return run

        async def commit(self):
            commits.append("commit")

        async def rollback(self):
            raise AssertionError("不应回滚成功路径")

        async def close(self):
            return None

    async def append_event(self, _session, _run, event_type, payload=None):
        appended.append((event_type, payload))

    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())
    monkeypatch.setattr(service_module.AgentRunService, "_append_event", append_event)
    monkeypatch.setenv("LLM_INPUT_COST_PER_1K_TOKENS_USD", "0.01")
    monkeypatch.setenv("LLM_OUTPUT_COST_PER_1K_TOKENS_USD", "0.02")

    await service_module.AgentRunService().record_observation(
        "run-obs",
        trace_id="trace-obs",
        model_events=[
            {
                "event_type": "voice.request.started",
                "channel": "voice",
                "model_name": "gpt-voice-a",
                "model_member": "member-a",
                "candidate_index": 1,
            },
            {
                "event_type": "voice.request.failed",
                "channel": "voice",
                "model_name": "gpt-voice-a",
                "model_member": "member-a",
                "candidate_index": 1,
                "duration_ms": 12,
                "error_type": "TimeoutError",
            },
            {
                "event_type": "voice.request.completed",
                "channel": "voice",
                "model_name": "gpt-voice-b",
                "model_member": "member-b",
                "candidate_index": 2,
                "fallback_index": 1,
                "duration_ms": 19,
                "input_tokens": 10,
                "output_tokens": 5,
            },
        ],
    )

    assert commits == ["commit"]
    assert run.trace_id == "trace-obs"
    assert run.model_provider == "voice"
    assert run.model_name == "gpt-voice-b"
    assert run.model_member == "member-b"
    assert run.request_latency_ms == 31
    assert run.input_tokens == 10
    assert run.output_tokens == 5
    assert run.fallback_count == 1
    assert run.fallback_path == [
        {
            "candidate_index": 1,
            "channel": "voice",
            "model_name": "gpt-voice-a",
            "model_member": "member-a",
            "status": "failed",
            "duration_ms": 12,
            "error_type": "TimeoutError",
        },
        {
            "candidate_index": 2,
            "channel": "voice",
            "model_name": "gpt-voice-b",
            "model_member": "member-b",
            "status": "completed",
            "duration_ms": 19,
            "error_type": None,
        },
    ]
    assert run.estimated_cost_usd == 0.0002
    assert run.model_error_type == "TimeoutError"
    assert [item[0] for item in appended] == [
        "voice.request.started",
        "voice.request.failed",
        "voice.request.completed",
    ]
    assert appended[-1][1]["trace_id"] == "trace-obs"
    assert "event_type" not in appended[-1][1]


@pytest.mark.asyncio
async def test_event_stream_replays_from_last_event_id_when_larger(monkeypatch):
    from types import SimpleNamespace
    from app.api import agent_runs

    now = datetime.now()
    run = SimpleNamespace(status="succeeded")
    event = SimpleNamespace(
        id=8,
        run_id="run-1",
        sequence=8,
        event_type="run.completed",
        stage="succeeded",
        payload={"ok": True},
        schema_version=1,
        created_at=now,
    )
    list_after_sequences: list[int] = []

    async def get(_run_id, _user_id):
        return run

    async def list_events(_run_id, _user_id, *, after_sequence, limit):
        list_after_sequences.append(after_sequence)
        assert limit == 200
        return [event] if after_sequence == 7 else []

    monkeypatch.setattr(agent_runs.service, "get", get)
    monkeypatch.setattr(agent_runs.service, "list_events", list_events)

    response = await agent_runs.stream_agent_run_events(
        "run-1",
        after_sequence=3,
        last_event_id="7",
        user_id="user-1",
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    assert list_after_sequences == [7, 8]
    assert chunks == [
        f'id: 8\nevent: run.completed\ndata: {json.dumps({"event_id": "8", "run_id": "run-1", "sequence": 8, "type": "run.completed", "stage": "succeeded", "payload": {"ok": True}, "schema_version": 1, "timestamp": now.isoformat()}, ensure_ascii=False)}\n\n'
    ]


@pytest.mark.asyncio
async def test_mark_cancelled_uses_cancelled_state_and_event(monkeypatch):
    from app.services.agent_runs import service as service_module

    now = datetime.now()
    run = AgentRunModel(
        id="run-cancel", user_id="user-1", task_type="interview_start", status="running", stage="loading_context",
        idempotency_key="turn-cancel", payload_encrypted="encrypted", result=None, error_message=None,
        attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=None,
    )
    appended: list[tuple[str, dict | None]] = []
    calls: list[str] = []

    class FakeSession:
        async def get(self, _model, run_id, with_for_update=False):
            assert run_id == "run-cancel"
            assert with_for_update is True
            return run

        async def commit(self):
            calls.append("commit")

        async def rollback(self):
            calls.append("rollback")

        async def close(self):
            calls.append("close")

    async def append_event(self, _session, _run, event_type, payload=None):
        appended.append((event_type, payload))

    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())
    monkeypatch.setattr(service_module.AgentRunService, "_append_event", append_event)

    await service_module.AgentRunService().mark_cancelled("run-cancel", "用户取消")

    assert run.status == "cancelled"
    assert run.stage == "cancelled"
    assert run.error_message == "用户取消"
    assert run.finished_at is not None
    assert appended == [("run.cancelled", {"message": "用户取消"})]
    assert calls == ["commit", "close"]
