"""AgentRun 序列化、payload 加密、运行门控与任务计划的单元测试。"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.db.models.agent_run import AgentRunModel
from app.domain.agent_runs import TASK_TYPE_INTERVIEW_REPORT, TASK_TYPE_RESUME_OPTIMIZE
from app.security.payload_crypto import (
    TaskPayloadConfigurationError,
    decrypt_payload,
    encrypt_payload,
)
from ai.runtime.agent_runs.service import (
    build_task_plan,
    serialize_run,
)
from ai.runtime.runtime_gate import LocalRunGate


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
    from ai.runtime import runtime_gate

    monkeypatch.setenv("TASK_QUEUE_ENABLED", "false")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    assert isinstance(runtime_gate.get_run_gate(), LocalRunGate)


def test_serialized_run_excludes_encrypted_payload_and_model_telemetry():
    now = datetime.now()
    run = AgentRunModel(
        id="run-1", user_id="user-1", task_type="interview_start", status="queued", stage="queued",
        session_id="session-1",
        idempotency_key="turn-1", payload_encrypted="never-expose", result=None, error_message=None,
        trace_id="trace-1",
        attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
    )

    public = serialize_run(run)

    assert public["run_id"] == "run-1"
    assert public["session_id"] == "session-1"
    assert public["session_title"] is None
    assert public["session_status"] is None
    assert public["session_question_count"] is None
    assert public["session_max_questions"] is None
    assert "payload_encrypted" not in public
    assert public["plan"][0] == {
        "id": "queued",
        "title": "等待执行资源",
        "status": "running",
    }
    assert public["max_attempts"] == 3
    assert public["trace_id"] == "trace-1"
    assert public["can_retry"] is False
    assert public["step_results"] == {}
    for key in {
        "model_provider",
        "model_name",
        "model_member",
        "request_latency_ms",
        "input_tokens",
        "output_tokens",
        "fallback_count",
        "fallback_path",
        "estimated_cost_usd",
        "model_error_type",
    }:
        assert key not in public


def test_serialized_run_includes_owned_session_title_without_payload():
    now = datetime.now()
    run = AgentRunModel(
        id="run-1", user_id="user-1", task_type="interview_start", status="queued", stage="queued",
        session_id="session-1", idempotency_key="turn-1", payload_encrypted="never-expose", result=None,
        error_message=None, attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
    )
    setattr(run, "session_title", "后端工程师模拟面试")
    setattr(run, "session_status", "active")
    setattr(run, "session_question_count", 0)
    setattr(run, "session_max_questions", 5)

    public = serialize_run(run)

    assert public["session_title"] == "后端工程师模拟面试"
    assert public["session_status"] == "active"
    assert public["session_question_count"] == 0
    assert public["session_max_questions"] == 5
    assert "payload_encrypted" not in public


@pytest.mark.asyncio
async def test_session_title_resolver_attaches_only_titles_returned_by_owned_query():
    from ai.runtime.agent_runs.service import AgentRunService

    class FakeSession:
        async def execute(self, statement):
            compiled = str(statement)
            assert "sessions.user_id" in compiled
            assert "sessions.session_id IN" in compiled
            return [SimpleNamespace(
                session_id="owned-session",
                title="Python 模拟面试",
                status="active",
                question_count=0,
                max_questions=5,
            )]

    owned_run = SimpleNamespace(session_id="owned-session")
    unowned_run = SimpleNamespace(session_id="other-user-session")

    await AgentRunService()._attach_owned_session_titles(
        FakeSession(), [owned_run, unowned_run], "user-1"
    )

    assert owned_run.session_title == "Python 模拟面试"
    assert owned_run.session_status == "active"
    assert owned_run.session_question_count == 0
    assert owned_run.session_max_questions == 5
    assert unowned_run.session_title is None
    assert unowned_run.session_status is None
    assert unowned_run.session_question_count is None
    assert unowned_run.session_max_questions is None


def test_failed_run_plan_marks_last_business_stage():
    plan = build_task_plan("interview_start", "loading_context", "failed")

    assert [step["status"] for step in plan] == ["completed", "failed", "pending"]


def test_generic_task_plans_are_task_specific():
    resume_plan = build_task_plan(TASK_TYPE_RESUME_OPTIMIZE, "optimizing", "running")
    report_plan = build_task_plan(TASK_TYPE_INTERVIEW_REPORT, "generating_reports", "running")

    assert [step["id"] for step in resume_plan] == ["queued", "preparing", "optimizing", "saving_result"]
    assert resume_plan[2]["status"] == "running"
    assert [step["id"] for step in report_plan] == [
        "queued",
        "loading_session",
        "generating_reports",
        "saving_report",
    ]
    assert report_plan[2]["status"] == "running"


@pytest.mark.asyncio
async def test_agent_run_trace_link_uses_owned_run_and_langfuse_sdk(monkeypatch):
    from app.api import agent_runs

    async def get_run(*, run_id, user_id):
        assert run_id == "run-1"
        assert user_id == "user-1"
        return {"run_id": run_id, "trace_id": "trace-1"}

    monkeypatch.setattr(agent_runs.agent_run_use_cases, "get_run", get_run)
    monkeypatch.setattr(
        agent_runs,
        "get_langfuse_trace_url",
        lambda trace_id: f"https://langfuse.example/project/p/traces/{trace_id}",
    )

    response = await agent_runs.get_agent_run_trace_link("run-1", user_id="user-1")

    assert response == {
        "available": True,
        "url": "https://langfuse.example/project/p/traces/trace-1",
        "message": None,
    }


@pytest.mark.asyncio
async def test_agent_run_trace_link_is_graceful_without_trace(monkeypatch):
    from app.api import agent_runs

    async def get_run(**_kwargs):
        return {"run_id": "run-1", "trace_id": None}

    monkeypatch.setattr(agent_runs.agent_run_use_cases, "get_run", get_run)

    response = await agent_runs.get_agent_run_trace_link("run-1", user_id="user-1")

    assert response["available"] is False
    assert response["url"] is None


@pytest.mark.asyncio
async def test_redis_run_gate_renews_owned_lock(monkeypatch):
    from ai.runtime import runtime_gate

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
    from app.db.models.agent_run import AgentRunEventModel
    from ai.runtime.agent_runs.service import serialize_event

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
