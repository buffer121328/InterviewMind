"""Focused AgentRun TTFT persistence and serialization coverage."""

import pytest

from app.clock import utc_now
from app.db.models.agent_run import AgentRunModel


def _run(*, first_token_duration_ms: int | None) -> AgentRunModel:
    now = utc_now()
    return AgentRunModel(
        id="run-ttft",
        user_id="user-1",
        task_type="interview_turn",
        status="running",
        stage="answering",
        idempotency_key="turn-ttft",
        payload_encrypted="encrypted",
        result=None,
        error_message=None,
        first_token_duration_ms=first_token_duration_ms,
        attempts=1,
        created_at=now,
        updated_at=now,
        started_at=now,
        finished_at=None,
    )


@pytest.mark.asyncio
async def test_observation_keeps_earliest_first_token_duration(monkeypatch) -> None:
    from ai.runtime.agent_runs import service as service_module

    run = _run(first_token_duration_ms=240)
    added = []

    class FakeSession:
        async def get(self, _model, run_id, with_for_update=False):
            assert run_id == run.id
            assert with_for_update is True
            return run

        async def scalar(self, _statement):
            return 0

        def add(self, item) -> None:
            added.append(item)

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            raise AssertionError("successful persistence must not roll back")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(service_module, "async_session", lambda: FakeSession())

    await service_module.AgentRunService().record_observation(
        run.id,
        observation_id="obs-ttft",
        model_events=[
            {"event_type": "llm.request.completed", "first_chunk_duration_ms": 180},
            {"event_type": "llm.request.completed", "first_chunk_duration_ms": 320},
            {"event_type": "llm.request.completed", "first_chunk_duration_ms": -1},
        ],
    )

    assert run.first_token_duration_ms == 180
    assert len(added) == 3
    assert service_module.serialize_run(run)["first_token_duration_ms"] == 180
