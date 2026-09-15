"""AgentRun 队列分发、outbox、恢复循环与 inline 模式的单元测试。"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models.agent_run import AgentRunModel
from app.schemas.interview.schemas import InterviewStartRequest


@pytest.mark.asyncio
async def test_recommendation_capture_is_rate_limited_before_run_creation():
    """过密的 BOSS 推荐采集请求不应进入队列等待执行。"""
    from ai.workflows.agent_runs import use_cases as workflow

    use_cases = workflow.AgentRunUseCases()
    create_queued_run = AsyncMock()
    use_cases.create_queued_run = create_queued_run

    with patch(
        "integrations.browser_automation.rate_limiter.check_rate",
        new=AsyncMock(return_value=(False, "推荐采集至少间隔 120 秒")),
    ):
        with pytest.raises(workflow.AgentRunConflict, match="间隔"):
            await use_cases.create_job_recommendation_capture(
                payload={"query": "Agent", "resume_content": "resume", "top_n": 3},
                user_id="user-1",
                idempotency_key="capture-1",
            )

    create_queued_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_automatic_interview_report_run_uses_session_id_for_grouping(monkeypatch):
    from ai.workflows.interview.lifecycle import completion

    created_kwargs = {}

    class FakeRunService:
        async def create_or_get(self, **kwargs):
            created_kwargs.update(kwargs)
            return SimpleNamespace(id="report-run", status="queued"), True

    class FakeSessionRepo:
        async def get_session(self, *_args, **_kwargs):
            return SimpleNamespace(
                session_id="session-1",
                metadata=SimpleNamespace(
                    resume_content="private resume",
                    job_description="private jd",
                    company_info="company",
                    interview_plan=[],
                    round_type="tech_initial",
                    max_questions=5,
                ),
                messages=[],
            )

        async def update_session(self, **_kwargs):
            return SimpleNamespace()

    direct_deliveries: list[str] = []
    monkeypatch.setattr(completion, "task_queue_enabled", lambda: True)
    monkeypatch.setattr(completion, "AgentRunService", FakeRunService)
    monkeypatch.setattr(completion, "SessionRepo", FakeSessionRepo)
    monkeypatch.setattr(
        completion,
        "enqueue_agent_run",
        direct_deliveries.append,
        raising=False,
    )

    dispatch_calls: list[int] = []

    async def dispatch_pending_outbox(*, limit, enqueue_fn):
        dispatch_calls.append(limit)
        return 1, 0

    monkeypatch.setattr(completion, "dispatch_pending_outbox", dispatch_pending_outbox)

    await completion.queue_or_run_session_reports(
        session_id="session-1",
        api_config={"model": "test"},
        user_id="user-1",
    )

    assert created_kwargs["task_type"] == completion.TASK_TYPE_INTERVIEW_REPORT
    assert created_kwargs["session_id"] == "session-1"
    assert created_kwargs["payload"]["report_source_version"].startswith("rsv1-")
    assert "private" not in created_kwargs["payload"]["report_source_version"]
    assert ":standard:" not in created_kwargs["idempotency_key"]
    assert dispatch_calls == [50]
    assert direct_deliveries == []


@pytest.mark.asyncio
async def test_queued_start_dispatches_only_run_id(monkeypatch):
    from ai.workflows.agent_runs import mutations as agent_run_mutations
    from ai.workflows.agent_runs import use_cases as agent_run_workflow
    from app.api import agent_runs

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
    monkeypatch.setattr(agent_run_mutations, "enqueue_agent_run", enqueue)
    monkeypatch.setattr(agent_run_mutations, "dispatch_pending_outbox", dispatch_pending_outbox)

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
    from ai.workflows.agent_runs import mutations as agent_run_mutations
    from ai.workflows.agent_runs import use_cases as agent_run_workflow
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

    monkeypatch.setattr(agent_run_workflow, "task_queue_enabled", lambda: True)
    async def get_session(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._session_repo, "get_session", get_session)
    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "fail", fail)
    monkeypatch.setattr(agent_run_mutations, "dispatch_pending_outbox", dispatch_pending_outbox)

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
    from ai.workflows.agent_runs import mutations as agent_run_mutations
    from ai.workflows.agent_runs import use_cases as agent_run_workflow
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

    monkeypatch.setattr(agent_run_workflow, "task_queue_enabled", lambda: True)
    async def get_session(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._session_repo, "get_session", get_session)
    monkeypatch.setattr(agent_run_workflow.agent_run_use_cases._service, "create_or_get", create_or_get)
    monkeypatch.setattr(agent_run_mutations, "enqueue_agent_run", dispatched.append)
    monkeypatch.setattr(agent_run_mutations, "dispatch_pending_outbox", dispatch_pending_outbox)

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
    from ai.workflows.agent_runs import use_cases as agent_run_workflow

    use_cases = agent_run_workflow.AgentRunUseCases()
    created_kwargs = {}

    async def get_session(session_id, *, user_id=None, **_kwargs):
        assert session_id == "session-1"
        assert user_id == "user-1"
        return SimpleNamespace(
            session_id="session-1",
            metadata=SimpleNamespace(
                resume_content="private resume",
                job_description="private jd",
                company_info="company",
                interview_plan=[],
                round_type="tech_initial",
                max_questions=5,
            ),
            messages=[],
        )

    async def update_session(**_kwargs):
        return SimpleNamespace()

    async def create_queued_run(**kwargs):
        created_kwargs.update(kwargs)
        return agent_run_workflow.AgentRunResponse(body={})

    monkeypatch.setattr(use_cases._session_repo, "get_session", get_session)
    monkeypatch.setattr(use_cases._session_repo, "update_session", update_session)
    monkeypatch.setattr(use_cases, "create_queued_run", create_queued_run)

    await use_cases.create_interview_report(
        payload={"session_id": "session-1"},
        user_id="user-1",
        idempotency_key="report-1",
    )

    assert created_kwargs["session_id"] == "session-1"
    assert created_kwargs["payload"]["report_source_version"].startswith("rsv1-")
    assert "private" not in created_kwargs["payload"]["report_source_version"]
    assert ":standard:" not in created_kwargs["idempotency_key"]


@pytest.mark.asyncio
async def test_interview_report_rejects_unowned_session_before_creating_run(monkeypatch):
    from ai.workflows.agent_runs import use_cases as agent_run_workflow

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
async def test_recovery_loop_dispatches_recovered_runs(monkeypatch):
    from ai.workflows.agent_runs.queue import recovery

    dispatch_calls = []

    class FakeService:
        async def recover_all_stale_runs(self, limit=200):
            return [SimpleNamespace(id="run-recovered")]

    async def dispatch_pending_outbox(*, limit, enqueue_fn):
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
    from ai.workflows.agent_runs.queue import recovery

    dispatch_calls: list[int] = []

    class FakeService:
        async def recover_all_stale_runs(self, limit=200):
            return [SimpleNamespace(id="run-bad"), SimpleNamespace(id="run-ok")]

        async def fail(self, *_args):
            raise AssertionError("Outbox 投递失败不应直接 fail run")

    async def dispatch_pending_outbox(*, limit, enqueue_fn):
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
async def test_inline_mode_persists_agent_run_and_deferred_result(monkeypatch):
    """Queue-disabled development mode still writes the AgentRun shown by Run Center."""
    from ai.workflows.agent_runs import mutations as agent_run_mutations
    from ai.workflows.agent_runs import use_cases as workflow
    from ai.workflows.agent_runs.contracts import DeferredExecutionResult

    run = SimpleNamespace(id="inline-run-1", status="running", stage="preparing", result=None)
    calls: list[tuple[str, object]] = []

    class FakeLease:
        async def release(self):
            calls.append(("release", None))

    class FakeGate:
        async def acquire(self):
            return FakeLease()

    class FakeService:
        async def create_inline_or_get(self, **kwargs):
            calls.append(("create", kwargs))
            return run, True

        async def mark_stage(self, run_id, stage):
            calls.append(("stage", (run_id, stage)))
            run.stage = stage

        async def succeed_with_result_writer(self, run_id, writer):
            calls.append(("succeed_deferred", run_id))
            run.result = await writer(SimpleNamespace())
            run.status = "succeeded"
            run.stage = "succeeded"

        async def succeed(self, *_args):
            raise AssertionError("deferred result must use the transactional writer")

        async def fail(self, *_args):
            raise AssertionError("successful inline task must not fail")

        async def get(self, run_id, user_id):
            assert (run_id, user_id) == ("inline-run-1", "owner-1")
            return run

    async def execute(_self, task_type, payload, user_id, progress):
        assert task_type == "resume_workspace"
        assert payload["_agent_run_id"] == "inline-run-1"
        assert user_id == "owner-1"
        await progress("content_optimization")

        async def persist(_session):
            return {"result_id": 9, "result": {"review": {"status": "pending"}}}

        return DeferredExecutionResult(persist=persist)

    monkeypatch.setenv("TASK_QUEUE_ENABLED", "false")
    monkeypatch.setattr(agent_run_mutations, "get_run_gate", lambda: FakeGate())
    monkeypatch.setattr(workflow.AgentRunUseCases, "_run_inline_task", execute)
    monkeypatch.setattr(agent_run_mutations, "serialize_run", lambda value: {
        "run_id": value.id,
        "status": value.status,
        "stage": value.stage,
        "result": value.result,
    })
    use_cases = workflow.AgentRunUseCases()
    use_cases._service = FakeService()

    response = await use_cases.create_queued_run(
        task_type="resume_workspace",
        payload={"resume_content": "private"},
        user_id="owner-1",
        idempotency_key="inline-key",
    )

    assert response.body["run_id"] == "inline-run-1"
    assert response.body["status"] == "succeeded"
    assert response.body["result"]["result_id"] == 9
    create_kwargs = next(value for name, value in calls if name == "create")
    assert create_kwargs["idempotency_key"] == "inline-key"
    assert ("stage", ("inline-run-1", "content_optimization")) in calls
    assert ("succeed_deferred", "inline-run-1") in calls
