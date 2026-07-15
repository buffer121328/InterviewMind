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

    async def create_or_get(**_kwargs):
        return run, True

    def enqueue(run_id: str) -> None:
        dispatched.append(run_id)

    monkeypatch.setattr(agent_runs, "task_queue_enabled", lambda: True)
    monkeypatch.setattr(agent_runs.service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_runs, "enqueue_interview_start", enqueue)

    response = await agent_runs.create_interview_start_run(
        InterviewStartRequest(thread_id="turn-1", mode="mock", resume_context="private resume"),
        user_id="user-1",
        idempotency_key="turn-1",
    )

    assert response.status_code == 202
    assert dispatched == ["run-1"]
    assert "private resume" not in response.body.decode()
    assert json.loads(response.body)["run_id"] == "run-1"


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

    async def create_or_get(**_kwargs):
        return run, False

    monkeypatch.setattr(agent_runs, "task_queue_enabled", lambda: True)
    monkeypatch.setattr(agent_runs.service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_runs, "enqueue_interview_start", dispatched.append)

    response = await agent_runs.create_interview_start_run(
        InterviewStartRequest(thread_id="turn-1", mode="mock", resume_context="private resume"),
        user_id="user-1",
        idempotency_key="turn-1",
    )

    assert response.status_code == 202
    assert dispatched == []
