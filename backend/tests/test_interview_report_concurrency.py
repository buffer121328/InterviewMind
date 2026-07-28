"""Regression tests for interview-report latency and orchestration."""

import asyncio

import pytest

from ai.workflows.interview import completion


@pytest.mark.asyncio
async def test_session_profile_and_weakness_start_concurrently(monkeypatch):
    """The two session report model calls overlap instead of adding their latencies."""
    started: set[str] = set()
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def fake_report(name, *_args, **_kwargs):
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await release.wait()

    async def fake_weakness(*_args, **_kwargs):
        await fake_report("weakness")

    async def fake_profile(*_args, **_kwargs):
        await fake_report("profile")

    monkeypatch.setattr(
        "ai.agents.interview.interview_analysis.trigger_weakness_analysis",
        fake_weakness,
    )
    monkeypatch.setattr(
        "ai.agents.interview.interview_analysis.trigger_background_analysis",
        fake_profile,
    )

    task = asyncio.create_task(
        completion.generate_session_reports(
            session_id="session-1",
            user_id="user-1",
            api_config={"smart": {"model": "demo"}},
            raise_on_error=True,
        )
    )
    await asyncio.wait_for(both_started.wait(), timeout=1)
    release.set()

    assert await task is None
    assert started == {"weakness", "profile"}
