"""AgentRun Outbox 的无外部依赖单元测试。"""

from datetime import datetime

import pytest

from app.infrastructure.db.models.agent_run import AgentRunEventModel, AgentRunModel, TaskOutboxModel
from app.infrastructure.runtime.agent_runs import outbox


def _outbox_item(run_id: str, *, now: datetime) -> TaskOutboxModel:
    return TaskOutboxModel(
        topic=outbox.AGENT_RUN_EXECUTE_TOPIC,
        message_key=run_id,
        payload={"run_id": run_id},
        status="pending",
        attempts=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
        dispatched_at=None,
        last_error=None,
    )


@pytest.mark.asyncio
async def test_create_or_get_writes_agent_run_outbox_in_same_session(monkeypatch):
    from app.infrastructure.runtime.agent_runs import service as service_module

    added = []
    committed = False

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def scalar(self, _statement):
            return None

        def add(self, item):
            added.append(item)

        async def flush(self):
            return None

        async def commit(self):
            nonlocal committed
            committed = True

        async def rollback(self):
            raise AssertionError("rollback should not be called")

        async def refresh(self, _item):
            return None

    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())
    monkeypatch.setattr(service_module, "encrypt_payload", lambda payload: "encrypted-payload")

    run, created = await service_module.AgentRunService().create_or_get(
        user_id="user-1",
        payload={"private": "payload"},
        idempotency_key="idem-1",
        task_type=service_module.TASK_TYPE_INTERVIEW_START,
    )

    assert created is True
    assert committed is True
    assert any(item is run for item in added if isinstance(item, AgentRunModel))
    assert len([item for item in added if isinstance(item, AgentRunEventModel)]) == 1
    outbox_items = [item for item in added if isinstance(item, TaskOutboxModel)]
    assert len(outbox_items) == 1
    assert outbox_items[0].topic == outbox.AGENT_RUN_EXECUTE_TOPIC
    assert outbox_items[0].message_key == run.id
    assert outbox_items[0].payload == {"run_id": run.id}
    assert outbox_items[0].status == "pending"


def test_dispatch_outbox_items_keeps_failed_item_retryable_then_marks_dispatched():
    now = datetime(2026, 7, 16, 12, 0, 0)
    bad = _outbox_item("run-bad", now=now)
    good = _outbox_item("run-good", now=now)
    dispatched: list[str] = []

    def flaky_enqueue(run_id: str) -> None:
        if run_id == "run-bad":
            raise RuntimeError("broker unavailable")
        dispatched.append(run_id)

    success, failed = outbox.dispatch_outbox_items([bad, good], enqueue_fn=flaky_enqueue, now=now)

    assert (success, failed) == (1, 1)
    assert dispatched == ["run-good"]
    assert good.status == "dispatched"
    assert good.dispatched_at == now
    assert bad.status == "failed"
    assert bad.attempts == 1
    assert bad.next_attempt_at > now
    assert bad.last_error == "broker unavailable"
    assert bad.last_error_type == "RuntimeError"
    assert bad.last_failure_reason == "dispatch_error"
    assert bad.last_attempt_at == now
    assert bad.last_attempt_duration_ms is not None

    success, failed = outbox.dispatch_outbox_items([bad], enqueue_fn=dispatched.append, now=now)

    assert (success, failed) == (1, 0)
    assert dispatched == ["run-good", "run-bad"]
    assert bad.status == "dispatched"
    assert bad.dispatched_at == now
    assert bad.last_attempt_at == now
    assert bad.last_attempt_duration_ms is not None
    assert bad.last_error is None
    assert bad.last_error_type is None
    assert bad.last_failure_reason is None


def test_classify_dispatch_error_for_operational_reason():
    assert outbox.classify_dispatch_error(KeyError("run_id")) == ("KeyError", "invalid_payload")
    assert outbox.classify_dispatch_error(ConnectionError("redis down")) == ("ConnectionError", "broker_unavailable")



@pytest.mark.asyncio
async def test_enqueue_agent_run_outbox_reuses_existing_message():
    now = datetime(2026, 7, 16, 12, 0, 0)
    existing = _outbox_item("run-1", now=now)
    existing.status = "dispatched"
    existing.attempts = 3
    existing.dispatched_at = now
    existing.last_attempt_at = now
    existing.last_attempt_duration_ms = 12
    existing.last_error = "old"
    existing.last_error_type = "RuntimeError"
    existing.last_failure_reason = "dispatch_error"
    added = []

    class FakeSession:
        async def scalar(self, _statement):
            return existing

        def add(self, item):
            added.append(item)

    item = await outbox.enqueue_agent_run_outbox(FakeSession(), "run-1", now=now)

    assert item is existing
    assert added == []
    assert existing.status == "pending"
    assert existing.attempts == 0
    assert existing.next_attempt_at == now
    assert existing.dispatched_at is None
    assert existing.last_attempt_at is None
    assert existing.last_attempt_duration_ms is None
    assert existing.last_error is None
    assert existing.last_error_type is None
    assert existing.last_failure_reason is None
