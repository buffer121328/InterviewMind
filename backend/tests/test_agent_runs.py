"""单用户任务队列的无外部依赖单元测试。"""

from datetime import datetime
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.db.models.agent_run import AgentRunModel
from app.schemas.schemas import InterviewStartRequest
from ai.runtime.agent_runs.crypto import (
    TaskPayloadConfigurationError,
    decrypt_payload,
    encrypt_payload,
)
from ai.runtime.agent_runs.service import (
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_RESUME_OPTIMIZE,
    build_interview_start_plan,
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
    assert "payload_encrypted" not in public
    assert public["plan"][0] == {
        "id": "queued",
        "title": "等待执行资源",
        "status": "running",
    }
    assert public["max_attempts"] == 3
    assert public["trace_id"] == "trace-1"
    assert public["can_retry"] is False
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

    public = serialize_run(run)

    assert public["session_title"] == "后端工程师模拟面试"
    assert "payload_encrypted" not in public


@pytest.mark.asyncio
async def test_session_title_resolver_attaches_only_titles_returned_by_owned_query():
    from types import SimpleNamespace

    from ai.runtime.agent_runs.service import AgentRunService

    class FakeSession:
        async def execute(self, statement):
            compiled = str(statement)
            assert "sessions.user_id" in compiled
            assert "sessions.session_id IN" in compiled
            return [SimpleNamespace(session_id="owned-session", title="Python 模拟面试")]

    owned_run = SimpleNamespace(session_id="owned-session")
    unowned_run = SimpleNamespace(session_id="other-user-session")

    await AgentRunService()._attach_owned_session_titles(
        FakeSession(), [owned_run, unowned_run], "user-1"
    )

    assert owned_run.session_title == "Python 模拟面试"
    assert unowned_run.session_title is None


@pytest.mark.asyncio
async def test_interview_session_backfill_updates_owned_string_references_in_one_batch(monkeypatch):
    from ai.runtime.agent_runs import service as service_module
    from ai.runtime.agent_runs.service import AgentRunService

    now = datetime.now()

    def run(run_id, task_type, payload_encrypted, *, user_id="user-1", session_id=None):
        return AgentRunModel(
            id=run_id, user_id=user_id, task_type=task_type, status="succeeded", stage="succeeded",
            session_id=session_id, idempotency_key=run_id, payload_encrypted=payload_encrypted,
            result=None, error_message=None, attempts=1, created_at=now, updated_at=now,
            started_at=now, finished_at=now,
        )

    thread_run = run("thread-run", "interview_start", "thread-payload")
    session_run = run("session-run", "interview_report", "session-payload")
    unowned_run = run("unowned-run", "interview_turn", "unowned-payload")
    failed_run = run("failed-run", "voice_interview_turn", "failed-payload")
    malformed_run = run("malformed-run", "interview_turn", "malformed-payload")
    non_interview_run = run("non-interview", "resume_optimize", "ignored-payload")
    decryptions = {
        "thread-payload": {"thread_id": "owned-thread", "sensitive": "never persisted"},
        "session-payload": {"session_id": "owned-session"},
        "unowned-payload": {"thread_id": "other-users-session"},
        "malformed-payload": {"thread_id": 42},
        "ignored-payload": {"thread_id": "must-not-be-decrypted"},
    }
    commits = 0

    class FakeSession:
        async def scalars(self, statement):
            compiled = str(statement)
            if "agent_runs" in compiled:
                assert "agent_runs.session_id IS NULL" in compiled
                return [thread_run, session_run, unowned_run, failed_run, malformed_run, non_interview_run]
            assert "sessions.user_id" in compiled
            return ["owned-thread", "owned-session"]

        async def commit(self):
            nonlocal commits
            commits += 1

        async def rollback(self):
            raise AssertionError("successful backfill must not roll back")

        async def close(self):
            return None

    class FakeUnitOfWork:
        def __init__(self, _factory):
            self.db = FakeSession()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            assert exc_type is None
            await self.db.commit()
            await self.db.close()
            return False

    def decrypt(payload_encrypted):
        if payload_encrypted == "failed-payload":
            raise TaskPayloadConfigurationError("payload unavailable")
        return decryptions[payload_encrypted]

    monkeypatch.setattr(service_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(service_module, "decrypt_payload", decrypt)

    updated = await AgentRunService().backfill_interview_session_ids("user-1")

    assert updated == 2
    assert thread_run.session_id == "owned-thread"
    assert session_run.session_id == "owned-session"
    assert unowned_run.session_id is None
    assert failed_run.session_id is None
    assert malformed_run.session_id is None
    assert non_interview_run.session_id is None
    assert commits == 1


@pytest.mark.asyncio
async def test_interview_session_backfill_is_idempotent_and_bounded(monkeypatch):
    from ai.runtime.agent_runs import service as service_module
    from ai.runtime.agent_runs.service import AgentRunService

    now = datetime.now()
    run = AgentRunModel(
        id="run-1", user_id="user-1", task_type="interview_start", status="succeeded", stage="succeeded",
        session_id=None, idempotency_key="run-1", payload_encrypted="encrypted", result=None,
        error_message=None, attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=now,
    )
    decrypt_calls = 0
    limits: list[dict] = []

    class FakeSession:
        async def scalars(self, statement):
            compiled = str(statement)
            if "agent_runs" in compiled:
                limits.append(statement.compile().params)
                return [run] if run.session_id is None else []
            return ["owned-session"]

        async def commit(self):
            return None

        async def rollback(self):
            return None

        async def close(self):
            return None

    class FakeUnitOfWork:
        def __init__(self, _factory):
            self.db = FakeSession()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            await self.db.commit()
            await self.db.close()
            return False

    def decrypt(_payload_encrypted):
        nonlocal decrypt_calls
        decrypt_calls += 1
        return {"thread_id": "owned-session"}

    monkeypatch.setattr(service_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(service_module, "decrypt_payload", decrypt)

    service = AgentRunService()
    assert await service.backfill_interview_session_ids("user-1", limit=10_000) == 1
    assert await service.backfill_interview_session_ids("user-1", limit=10_000) == 0
    assert decrypt_calls == 1
    assert any(value == 200 for params in limits for value in params.values())


@pytest.mark.asyncio
async def test_automatic_interview_report_run_uses_session_id_for_grouping(monkeypatch):
    from ai.workflows.interview import completion

    created_kwargs = {}

    class FakeRunService:
        async def create_or_get(self, **kwargs):
            created_kwargs.update(kwargs)
            return SimpleNamespace(id="report-run", status="queued"), True

    monkeypatch.setattr(completion, "task_queue_enabled", lambda: True)
    monkeypatch.setattr(completion, "AgentRunService", FakeRunService)
    monkeypatch.setattr(completion, "enqueue_agent_run", lambda run_id: None)

    await completion.queue_or_run_session_reports(
        session_id="session-1",
        api_config={"model": "test"},
        user_id="user-1",
    )

    assert created_kwargs["task_type"] == completion.TASK_TYPE_INTERVIEW_REPORT
    assert created_kwargs["session_id"] == "session-1"


@pytest.mark.asyncio
async def test_grouped_runs_paginate_sessions_and_include_all_matching_children(monkeypatch):
    from ai.runtime.agent_runs import service as service_module

    now = datetime.now()
    session_runs = [
        SimpleNamespace(id="run-2", session_id="session-1", created_at=now),
        SimpleNamespace(id="run-1", session_id="session-1", created_at=now),
    ]
    other_runs = [SimpleNamespace(id="run-other", session_id=None, created_at=now)]
    statements = []

    class FakeSession:
        def __init__(self):
            self.execute_calls = 0
            self.scalars_calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            statements.append(str(statement))
            self.execute_calls += 1
            if self.execute_calls == 1:
                return SimpleNamespace(all=lambda: [SimpleNamespace(session_id="session-1")])
            return [SimpleNamespace(session_id="session-1", title="Python 模拟面试")]

        async def scalar(self, statement):
            statements.append(str(statement))
            return 2

        async def scalars(self, statement):
            statements.append(str(statement))
            self.scalars_calls += 1
            return iter(session_runs if self.scalars_calls == 1 else other_runs)

    fake_session = FakeSession()
    monkeypatch.setattr(service_module, "async_session", lambda: fake_session)

    groups, returned_other_runs, total = await service_module.AgentRunService().list_grouped_runs(
        "user-1",
        status="succeeded",
        task_type="interview_report",
        limit=1,
        offset=0,
    )

    assert total == 2
    assert [(session_id, [run.id for run in runs]) for session_id, runs in groups] == [
        ("session-1", ["run-2", "run-1"])
    ]
    assert [run.id for run in returned_other_runs] == ["run-other"]
    assert all(run.session_title == "Python 模拟面试" for run in session_runs)
    assert returned_other_runs[0].session_title is None
    assert all("agent_runs.user_id" in statement for statement in statements[:-1])
    assert any("agent_runs.status" in statement for statement in statements)
    assert any("agent_runs.task_type" in statement for statement in statements)


@pytest.mark.asyncio
async def test_grouped_runs_api_forwards_child_filters_and_group_pagination(monkeypatch):
    from app.api import agent_runs

    received = {}

    async def list_grouped_runs(**kwargs):
        received.update(kwargs)
        return {"success": True, "groups": [], "total": 0, "session_total": 0, "other_total": 0}

    monkeypatch.setattr(agent_runs.agent_run_use_cases, "list_grouped_runs", list_grouped_runs)

    response = await agent_runs.list_grouped_agent_runs(
        user_id="user-1",
        status_filter="succeeded",
        task_type="interview_report",
        limit=10,
        offset=20,
    )

    assert response["success"] is True
    assert received == {
        "user_id": "user-1",
        "status": "succeeded",
        "task_type": "interview_report",
        "limit": 10,
        "offset": 20,
    }


@pytest.mark.asyncio
async def test_backfill_session_links_api_uses_authenticated_owner_and_returns_count(monkeypatch):
    from app.api import agent_runs

    received: dict[str, str] = {}

    async def backfill_session_links(*, user_id: str):
        received["user_id"] = user_id
        return {"updated": 2}

    monkeypatch.setattr(agent_runs.agent_run_use_cases, "backfill_session_links", backfill_session_links)

    response = await agent_runs.backfill_agent_run_session_links(user_id="user-1")

    assert response == {"updated": 2}
    assert received == {"user_id": "user-1"}


@pytest.mark.asyncio
async def test_backfill_session_links_use_case_delegates_without_payload(monkeypatch):
    from ai.workflows.agent_runs import AgentRunUseCases

    use_cases = AgentRunUseCases()
    received: dict[str, str] = {}

    async def backfill_interview_session_ids(user_id: str) -> int:
        received["user_id"] = user_id
        return 1

    monkeypatch.setattr(use_cases._service, "backfill_interview_session_ids", backfill_interview_session_ids)

    assert await use_cases.backfill_session_links(user_id="user-1") == {"updated": 1}
    assert received == {"user_id": "user-1"}


def test_agent_run_session_grouping_index_is_owner_scoped():
    index = next(
        index
        for index in AgentRunModel.__table__.indexes
        if index.name == "idx_agent_runs_user_session_created"
    )

    assert [column.name for column in index.columns] == ["user_id", "session_id", "created_at"]


def test_session_id_migration_uses_the_model_owner_scoped_index(monkeypatch):
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260727_01_agent_run_session_id.py"
    )
    spec = importlib.util.spec_from_file_location("agent_run_session_id_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operations = []

    monkeypatch.setattr(migration.op, "add_column", lambda *args: operations.append(("add_column", args)))
    monkeypatch.setattr(migration.op, "create_index", lambda *args: operations.append(("create_index", args)))
    monkeypatch.setattr(migration.op, "drop_index", lambda *args, **kwargs: operations.append(("drop_index", args, kwargs)))
    monkeypatch.setattr(migration.op, "drop_column", lambda *args: operations.append(("drop_column", args)))

    migration.upgrade()
    migration.downgrade()

    assert ("create_index", ("idx_agent_runs_user_session_created", "agent_runs", ["user_id", "session_id", "created_at"])) in operations
    assert all("ix_agent_runs_session_id" not in operation[1] for operation in operations)


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
async def test_queued_start_dispatches_only_run_id(monkeypatch):
    from app.api import agent_runs
    from ai.workflows import agent_runs as agent_run_workflow

    now = datetime.now()
    run = AgentRunModel(
        id="run-1", user_id="user-1", task_type="interview_start", status="queued", stage="queued",
        idempotency_key="turn-1", payload_encrypted="encrypted", result=None, error_message=None,
        attempts=0, created_at=now, updated_at=now, started_at=None, finished_at=None,
    )
    dispatched: list[str] = []
    dispatch_calls: list[int] = []

    create_kwargs = {}

    async def create_or_get(**kwargs):
        create_kwargs.update(kwargs)
        return run, True

    def enqueue(run_id: str) -> None:
        dispatched.append(run_id)

    async def dispatch_pending_outbox(*, limit, enqueue_fn):
        dispatch_calls.append(limit)
        enqueue_fn(run.id)
        return 1, 0

    monkeypatch.setattr(agent_run_workflow, "task_queue_enabled", lambda: True)
    async def get_session(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._session_repo, "get_session", get_session)
    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_run_workflow, "enqueue_agent_run", enqueue)
    monkeypatch.setattr(agent_run_workflow, "dispatch_pending_outbox", dispatch_pending_outbox)

    response = await agent_runs.create_interview_start_run(
        InterviewStartRequest(thread_id="turn-1", mode="mock", resume_context="private resume"),
        user_id="user-1",
        idempotency_key="turn-1",
    )

    assert response.status_code == 202
    assert dispatched == ["run-1"]
    assert dispatch_calls == [50]
    assert create_kwargs["session_id"] == "turn-1"
    assert "private resume" not in response.body.decode()
    assert json.loads(response.body)["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_queued_start_keeps_run_retryable_when_outbox_dispatch_fails(monkeypatch):
    from app.api import agent_runs
    from ai.workflows import agent_runs as agent_run_workflow

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

    monkeypatch.setattr(agent_run_workflow, "task_queue_enabled", lambda: True)
    async def get_session(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._session_repo, "get_session", get_session)
    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "fail", fail)
    monkeypatch.setattr(agent_run_workflow, "dispatch_pending_outbox", dispatch_pending_outbox)

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
    from ai.workflows import agent_runs as agent_run_workflow

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

    monkeypatch.setattr(agent_run_workflow, "task_queue_enabled", lambda: True)
    async def get_session(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._session_repo, "get_session", get_session)
    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_run_workflow, "enqueue_agent_run", dispatched.append)
    monkeypatch.setattr(agent_run_workflow, "dispatch_pending_outbox", dispatch_pending_outbox)

    response = await agent_runs.create_interview_start_run(
        InterviewStartRequest(thread_id="turn-1", mode="mock", resume_context="private resume"),
        user_id="user-1",
        idempotency_key="turn-1",
    )

    assert response.status_code == 202
    assert dispatched == []
    assert dispatch_calls == []


@pytest.mark.asyncio
async def test_interview_report_run_uses_owned_session_id(monkeypatch):
    from types import SimpleNamespace

    from ai.workflows import agent_runs as agent_run_workflow

    use_cases = agent_run_workflow.AgentRunUseCases()
    created_kwargs = {}

    async def get_session(session_id, *, user_id=None, **_kwargs):
        assert session_id == "session-1"
        assert user_id == "user-1"
        return SimpleNamespace()

    async def create_queued_run(**kwargs):
        created_kwargs.update(kwargs)
        return agent_run_workflow.AgentRunResponse(payload={})

    monkeypatch.setattr(use_cases._session_repo, "get_session", get_session)
    monkeypatch.setattr(use_cases, "create_queued_run", create_queued_run)

    await use_cases.create_interview_report(
        payload={"session_id": "session-1"},
        user_id="user-1",
        idempotency_key="report-1",
    )

    assert created_kwargs["session_id"] == "session-1"


@pytest.mark.asyncio
async def test_interview_report_rejects_unowned_session_before_creating_run(monkeypatch):
    from ai.workflows import agent_runs as agent_run_workflow

    use_cases = agent_run_workflow.AgentRunUseCases()

    async def get_session(*_args, **_kwargs):
        return None

    async def create_queued_run(**_kwargs):
        raise AssertionError("不应为无权会话创建任务")

    monkeypatch.setattr(use_cases._session_repo, "get_session", get_session)
    monkeypatch.setattr(use_cases, "create_queued_run", create_queued_run)

    with pytest.raises(agent_run_workflow.AgentRunNotFound):
        await use_cases.create_interview_report(
            payload={"session_id": "other-user-session"},
            user_id="user-1",
            idempotency_key="report-1",
        )


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


@pytest.mark.asyncio
async def test_cancel_api_returns_cancel_requested_for_running_run(monkeypatch):
    from app.api import agent_runs
    from ai.workflows import agent_runs as agent_run_workflow

    now = datetime.now()
    run = AgentRunModel(
        id="run-running", user_id="user-1", task_type="interview_start", status="cancel_requested", stage="loading_context",
        idempotency_key="turn-running", payload_encrypted="encrypted", result=None, error_message="正在请求取消当前任务",
        attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=None,
    )

    async def cancel(_run_id, _user_id):
        return run

    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "cancel", cancel)

    response = await agent_runs.cancel_agent_run("run-running", user_id="user-1")

    assert response["status"] == "cancel_requested"
    assert response["can_cancel"] is True


@pytest.mark.asyncio
async def test_recovery_loop_dispatches_recovered_runs(monkeypatch):
    from types import SimpleNamespace
    from ai.runtime.agent_runs import recovery

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
    from ai.runtime.agent_runs import recovery

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
    from ai.runtime.agent_runs import service as service_module

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

    monkeypatch.setenv("TASK_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
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
    from ai.runtime.agent_runs import service as service_module

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
async def test_record_observation_persists_trace_only(monkeypatch):
    from ai.runtime.agent_runs import service as service_module

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

    monkeypatch.setenv("TASK_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())
    monkeypatch.setattr(service_module.AgentRunService, "_append_event", append_event)

    await service_module.AgentRunService().record_observation(
        "run-obs",
        trace_id="trace-obs",
        model_events=[
            {
                "event_type": "voice.request.completed",
                "channel": "voice",
                "model_name": "gpt-voice-b",
                "model_member": "member-b",
                "duration_ms": 19,
                "input_tokens": 10,
                "output_tokens": 5,
            },
        ],
    )

    assert commits == ["commit"]
    assert run.trace_id == "trace-obs"
    assert run.updated_at >= now
    assert appended == []


@pytest.mark.asyncio
async def test_create_or_get_emits_prompt_version_in_created_event(monkeypatch):
    from ai.runtime.agent_runs import service as service_module

    appended: list[tuple[str, dict | None]] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def scalar(self, _stmt):
            return None

        def add(self, _item):
            return None

        async def flush(self):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

        async def refresh(self, _item):
            return None

        async def close(self):
            return None

    async def append_event(self, _session, _run, event_type, payload=None):
        appended.append((event_type, payload))

    monkeypatch.setenv("TASK_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())
    monkeypatch.setattr(service_module.AgentRunService, "_append_event", append_event)

    run, created = await service_module.AgentRunService().create_or_get(
        user_id="user-1",
        payload={"thread_id": "turn-1"},
        idempotency_key="turn-1",
        task_type="interview_start",
        session_id="turn-1",
    )

    assert created is True
    assert run.session_id == "turn-1"
    assert run.created_at is not None
    assert appended and appended[0][0] == "run.created"
    assert appended[0][1]["prompt_name"] == "interview.planner"
    assert appended[0][1]["prompt_version"] == "1"


@pytest.mark.asyncio
async def test_event_stream_replays_from_last_event_id_when_larger(monkeypatch):
    from types import SimpleNamespace
    from app.api import agent_runs
    from ai.workflows import agent_runs as agent_run_workflow

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

    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "get", get)
    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "list_events", list_events)

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
    from ai.runtime.agent_runs import service as service_module

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

    monkeypatch.setenv("TASK_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())
    monkeypatch.setattr(service_module.AgentRunService, "_append_event", append_event)

    await service_module.AgentRunService().mark_cancelled("run-cancel", "用户取消")

    assert run.status == "cancelled"
    assert run.stage == "cancelled"
    assert run.error_message == "用户取消"
    assert run.finished_at is not None
    assert appended == [("run.cancelled", {"message": "用户取消"})]
    assert calls == ["commit", "close"]


@pytest.mark.asyncio
async def test_record_governance_event_persists_sanitized_tool_audit(monkeypatch):
    from ai.runtime.agent_runs import service as service_module

    now = datetime.now()
    run = AgentRunModel(
        id="run-governance",
        user_id="user-1",
        task_type="resume_optimize",
        status="running",
        stage="optimizing",
        idempotency_key="governance-key",
        payload_encrypted="encrypted",
        result=None,
        error_message=None,
        attempts=1,
        created_at=now,
        updated_at=now,
        started_at=now,
        finished_at=None,
    )
    appended: list[tuple[str, dict | None]] = []

    class FakeSession:
        async def get(self, _model, run_id, with_for_update=False):
            assert run_id == "run-governance"
            assert with_for_update is True
            return run

        async def commit(self):
            return None

        async def rollback(self):
            raise AssertionError("不应回滚成功路径")

        async def close(self):
            return None

    class FakeUnitOfWork:
        def __init__(self, _factory):
            self.db = FakeSession()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            await self.db.commit()
            await self.db.close()
            return False

    async def append_event(self, _session, _run, event_type, payload=None):
        appended.append((event_type, payload))

    monkeypatch.setattr(service_module, "UnitOfWork", FakeUnitOfWork)
    monkeypatch.setattr(service_module.AgentRunService, "_append_event", append_event)

    persisted = await service_module.AgentRunService().record_governance_event(
        "run-governance",
        user_id="user-1",
        event_type="tool.execution",
        payload={"api_key": "secret", "output_summary": "x" * 500},
    )

    assert persisted is True
    assert appended[0][0] == "tool.execution"
    assert appended[0][1]["api_key"] == "***REDACTED***"
    assert len(appended[0][1]["output_summary"]) == 300
