"""AgentRun 分组列表、状态生命周期、事件流与治理事件的单元测试。"""

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.db.models.agent_run import AgentRunModel


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
            return [SimpleNamespace(
                session_id="session-1",
                title="Python 模拟面试",
                status="active",
                question_count=0,
                max_questions=5,
            )]

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
    assert all(run.session_status == "active" for run in session_runs)
    assert all(run.session_question_count == 0 for run in session_runs)
    assert all(run.session_max_questions == 5 for run in session_runs)
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
async def test_run_list_api_forwards_session_filter(monkeypatch):
    """The report dialog can recover exactly the run linked to its session."""
    from app.api import agent_runs

    received = {}

    async def list_runs(**kwargs):
        received.update(kwargs)
        return {"success": True, "runs": [], "total": 0, "limit": 1, "offset": 0}

    monkeypatch.setattr(agent_runs.agent_run_use_cases, "list_runs", list_runs)

    response = await agent_runs.list_agent_runs(
        user_id="user-1",
        status_filter=None,
        task_type="interview_report",
        session_id="session-1",
        limit=1,
        offset=0,
    )

    assert response["success"] is True
    assert received == {
        "user_id": "user-1",
        "status": None,
        "task_type": "interview_report",
        "session_id": "session-1",
        "limit": 1,
        "offset": 0,
    }


def test_agent_run_session_grouping_index_is_owner_scoped():
    index = next(
        index
        for index in AgentRunModel.__table__.indexes
        if index.name == "idx_agent_runs_user_session_created"
    )

    assert [column.name for column in index.columns] == ["user_id", "session_id", "created_at"]


def test_legacy_agent_run_backfill_interface_is_removed():
    backend_root = Path(__file__).resolve().parents[2]
    sources = [
        (backend_root / "app" / "api" / "agent_runs.py").read_text(),
        (backend_root / "ai" / "workflows" / "agent_runs.py").read_text(),
        (backend_root / "ai" / "runtime" / "agent_runs" / "service.py").read_text(),
    ]
    combined = "\n".join(sources)
    assert "backfill-session-links" not in combined
    assert "backfill_session_links" not in combined
    assert "backfill_interview_session_ids" not in combined


def test_session_id_migration_uses_the_model_owner_scoped_index(monkeypatch):
    migration_path = (
        Path(__file__).resolve().parents[2]
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
    from app.clock import utc_now

    now = utc_now()
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
    )

    assert commits == ["commit"]
    assert run.trace_id == "trace-obs"
    assert run.updated_at >= now
    assert appended == []


@pytest.mark.asyncio
async def test_record_observation_persists_earliest_first_token_duration(monkeypatch):
    from ai.runtime.agent_runs import service as service_module
    from app.clock import utc_now

    now = utc_now()
    run = AgentRunModel(
        id="run-ttft", user_id="user-1", task_type="interview_turn", status="running", stage="answering",
        idempotency_key="turn-ttft", payload_encrypted="encrypted", result=None, error_message=None,
        first_token_duration_ms=240, attempts=1, created_at=now, updated_at=now, started_at=now, finished_at=None,
    )
    added = []

    class FakeSession:
        async def get(self, _model, run_id, with_for_update=False):
            assert run_id == "run-ttft"
            assert with_for_update is True
            return run

        async def scalar(self, _statement):
            return 0

        def add(self, item):
            added.append(item)

        async def commit(self):
            return None

        async def rollback(self):
            raise AssertionError("不应回滚成功路径")

        async def close(self):
            return None

    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())

    await service_module.AgentRunService().record_observation(
        "run-ttft",
        observation_id="obs-ttft",
        model_events=[
            {"event_type": "llm.request.completed", "first_chunk_duration_ms": 180},
            {"event_type": "llm.request.completed", "first_chunk_duration_ms": 320},
            {"event_type": "llm.request.completed", "first_chunk_duration_ms": -1},
        ],
    )

    assert run.first_token_duration_ms == 180
    assert len(added) == 3


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
    assert appended[0][1]["prompt_version"] == "3"


@pytest.mark.asyncio
async def test_event_stream_replays_from_last_event_id_when_larger(monkeypatch):
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
