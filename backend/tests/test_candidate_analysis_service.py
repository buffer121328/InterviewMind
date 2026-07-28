"""Regression tests for owner-scoped session report analysis."""

from unittest.mock import AsyncMock

import pytest

from ai.workflows.analysis.analysis_service import (
    CandidateAnalysisService,
    WeaknessAnalysisService,
)
from app.schemas.candidate_profile import CandidateProfile, DimensionScore


def _profile() -> CandidateProfile:
    """Build a compact valid profile fixture for service-boundary tests."""
    dimension = DimensionScore(score=8, evidence="回答证据")
    return CandidateProfile(
        professional_competence=dimension,
        execution_results=dimension,
        logic_problem_solving=dimension,
        communication=dimension,
        growth_potential=dimension,
        collaboration=dimension,
        skill_tags=["FastAPI"],
        last_updated="2026-07-28T10:00:00",
    )


@pytest.mark.asyncio
async def test_candidate_analysis_accepts_user_id_and_owner_scopes_persistence():
    """The AgentRun caller may pass user_id and every profile read/write keeps it."""
    service = CandidateAnalysisService()
    service.session_repo = AsyncMock()
    service.session_repo.get_profile.return_value = None
    service.session_repo.save_profile.return_value = True
    service._perform_analysis = AsyncMock(return_value=_profile())

    result = await service.analyze_candidate(
        "session-1",
        "resume",
        "jd",
        "company",
        [{"question": "Q", "answer": "A"}],
        {"smart": {"model": "demo"}},
        user_id="user-1",
    )

    assert result.skill_tags == ["FastAPI"]
    service.session_repo.get_profile.assert_awaited_once_with(
        "session-1",
        user_id="user-1",
    )
    saved_args = service.session_repo.save_profile.await_args
    assert saved_args.args[0] == "session-1"
    assert saved_args.kwargs["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_candidate_analysis_propagates_model_failure_to_agent_run():
    """A failed model call must fail the AgentRun instead of persisting an '分析中' placeholder."""
    service = CandidateAnalysisService()
    service.session_repo = AsyncMock()
    service.session_repo.get_profile.return_value = None
    service._perform_analysis = AsyncMock(side_effect=RuntimeError("model failed"))

    with pytest.raises(RuntimeError, match="model failed"):
        await service.analyze_candidate(
            "session-1",
            "resume",
            "jd",
            "company",
            [{"question": "Q", "answer": "A"}],
            user_id="user-1",
        )

    service.session_repo.save_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_weakness_analysis_propagates_model_failure(monkeypatch):
    """An empty success report must not hide a failed weakness-model request."""
    async def fail_invoke(*_args, **_kwargs):
        raise RuntimeError("model failed")

    monkeypatch.setattr(
        "ai.workflows.analysis.analysis_service.invoke_structured",
        fail_invoke,
    )

    with pytest.raises(RuntimeError, match="model failed"):
        await WeaknessAnalysisService().generate_weakness_report(
            session_id="session-1",
            resume="resume",
            job_description="jd",
            company_info="company",
            qa_history=[{"question": "Q", "answer": "A"}],
        )
