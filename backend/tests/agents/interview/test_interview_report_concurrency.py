"""Regression tests for single-call interview-report orchestration."""

from unittest.mock import AsyncMock

import pytest

from ai.workflows.interview.lifecycle import completion


@pytest.mark.asyncio
async def test_session_profile_and_weakness_share_one_analysis_call(monkeypatch):
    """The report workflow invokes the combined analysis boundary exactly once."""
    trigger = AsyncMock()
    monkeypatch.setattr(
        "ai.agents.interview.interview_analysis.trigger_session_report_analysis",
        trigger,
    )

    await completion.generate_session_reports(
        session_id="session-1",
        user_id="user-1",
        api_config={"smart": {"model": "demo"}},
        raise_on_error=True,
    )

    trigger.assert_awaited_once_with(
        "session-1",
        {"smart": {"model": "demo"}},
        user_id="user-1",
        raise_on_error=True,
    )
