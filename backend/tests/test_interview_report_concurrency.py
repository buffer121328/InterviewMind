"""Regression tests for interview-report latency and orchestration."""

import asyncio

import pytest

from ai.workflows.agent_tasks import interview_report


@pytest.mark.asyncio
async def test_weakness_and_overall_profile_start_concurrently(monkeypatch):
    """Both independent post-profile model calls should overlap instead of adding their latencies."""
    started: set[str] = set()
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def fake_weakness(*_args, **_kwargs):
        started.add("weakness")
        if len(started) == 2:
            both_started.set()
        await release.wait()

    async def fake_overall(*, user_id: str, api_config: dict | None):
        assert user_id == "user-1"
        assert api_config == {"smart": {"model": "demo"}}
        started.add("overall")
        if len(started) == 2:
            both_started.set()
        await release.wait()
        return {"score": 8}, None

    monkeypatch.setattr(
        "ai.agents.interview.interview_analysis.trigger_weakness_analysis",
        fake_weakness,
    )
    monkeypatch.setattr(interview_report, "_generate_overall_profile", fake_overall)

    task = asyncio.create_task(
        interview_report._generate_weakness_and_overall(
            session_id="session-1",
            user_id="user-1",
            api_config={"smart": {"model": "demo"}},
        )
    )
    await asyncio.wait_for(both_started.wait(), timeout=1)
    release.set()

    assert await task == ({"score": 8}, None)
    assert started == {"weakness", "overall"}
