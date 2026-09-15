"""Acceptance contracts for the remaining Phase 2 result-consumption loop."""

from app.domain.ability_growth import build_ability_growth_record, build_ability_profile_progress


def _profile(score: float) -> dict:
    """Build a minimal six-dimension profile fixture."""
    return {
        key: {"score": score, "evidence": "e"}
        for key in (
            "professional_competence",
            "execution_results",
            "logic_problem_solving",
            "communication",
            "growth_potential",
            "collaboration",
        )
    }


def test_growth_record_uses_persisted_sources_and_deterministic_changes() -> None:
    """The growth record must compare persisted scores without invoking a model."""
    result = build_ability_growth_record(
        overall={"profile": _profile(8), "updated_at": "2026-08-04T10:00:00"},
        source_rows=[
            {
                "session_id": "latest",
                "title": "甲公司",
                "updated_at": "2026-08-04T09:00:00",
                "company_profile": {"profile": _profile(8)},
            },
            {
                "session_id": "previous",
                "title": "乙公司",
                "updated_at": "2026-08-01T09:00:00",
                "company_profile": {"profile": _profile(6.5)},
            },
        ],
    )

    assert result["sample_count"] == 2
    assert result["sources"][0]["session_id"] == "latest"
    assert result["dimension_changes"]["communication"] == 1.5


def test_growth_record_does_not_invent_trends_for_one_source() -> None:
    """A single source is evidence, but not a trend."""
    result = build_ability_growth_record(
        overall={"profile": _profile(7), "updated_at": "2026-08-04T10:00:00"},
        source_rows=[
            {
                "session_id": "only",
                "updated_at": "2026-08-04T09:00:00",
                "company_profile": {"profile": _profile(7)},
            }
        ],
    )

    assert result["sample_count"] == 1
    assert result["dimension_changes"] == {}

import pytest
from unittest.mock import AsyncMock

import ai.workflows.applications.use_cases as application_module
from ai.workflows.applications.use_cases import ApplicationNotFound, ApplicationUseCases
from app.schemas.jobs.job_application import ApplicationDetail, ApplicationResumeLinkRequest


def _application(*, generated_resume_id: int | None = None, custom_resume_id: int | None = None) -> ApplicationDetail:
    """Build one application detail fixture without a hydrated resume asset."""
    return ApplicationDetail(
        id=1,
        user_id="owner",
        company_name="甲公司",
        job_title="Agent 工程师",
        generated_resume_id=generated_resume_id,
        custom_resume_id=custom_resume_id,
        latest_status="saved",
        priority="medium",
        created_at="2026-08-04T10:00:00",
        updated_at="2026-08-04T10:00:00",
    )


@pytest.mark.asyncio
async def test_application_resume_link_validates_owner_and_returns_asset(monkeypatch) -> None:
    """Only a generated resume visible to the same owner can be linked."""
    generation_repo = AsyncMock()
    generation_repo.get_generated_resume.return_value = {
        "id": 7,
        "title": "Agent 工程师-v2",
        "job_description": "Agent",
        "content": "# Resume",
        "created_at": "2026-08-04T09:00:00",
    }
    monkeypatch.setattr(application_module, "get_generation_repo", lambda: generation_repo)
    monkeypatch.setattr(application_module.job_application_repo, "get_application", AsyncMock(return_value=_application()))
    monkeypatch.setattr(
        application_module.job_application_repo,
        "set_linked_resume",
        AsyncMock(return_value=_application(generated_resume_id=7)),
    )

    response = await ApplicationUseCases().set_application_resume(
        application_id=1,
        user_id="owner",
        request=ApplicationResumeLinkRequest(resume_id=7),
    )

    assert response.application.linked_resume is not None
    assert response.application.linked_resume.id == 7
    generation_repo.get_generated_resume.assert_awaited_with(7, "owner")


@pytest.mark.asyncio
async def test_application_resume_link_rejects_foreign_resume(monkeypatch) -> None:
    """A missing owner-scoped lookup must reject the replacement before writing."""
    generation_repo = AsyncMock()
    generation_repo.get_generated_resume.return_value = None
    monkeypatch.setattr(application_module, "get_generation_repo", lambda: generation_repo)
    monkeypatch.setattr(application_module.job_application_repo, "get_application", AsyncMock(return_value=_application()))
    write = AsyncMock()
    monkeypatch.setattr(application_module.job_application_repo, "set_linked_resume", write)

    with pytest.raises(ApplicationNotFound):
        await ApplicationUseCases().set_application_resume(
            application_id=1,
            user_id="owner",
            request=ApplicationResumeLinkRequest(resume_id=99),
        )

    write.assert_not_awaited()

from types import SimpleNamespace

from ai.workflows.resume import generation as generation_module
from ai.workflows.resume.generation import (
    ResumeGenerationConflict,
    ResumeGenerationUseCases,
)


@pytest.mark.asyncio
async def test_needs_input_rejects_wrong_status_before_creating_run(monkeypatch) -> None:
    """A completed or otherwise non-waiting session cannot create a continuation run."""
    monkeypatch.setattr(
        generation_module.session_store,
        "get",
        AsyncMock(return_value=SimpleNamespace(status="completed", questions=["q"], agent_run_id=None)),
    )
    run_service = AsyncMock()

    with pytest.raises(ResumeGenerationConflict):
        await ResumeGenerationUseCases()._validate_answer_submission(
            request=SimpleNamespace(session_id="session-1", answers={"q": "a"}),
            user_id="owner",
            run_service=run_service,
        )

    run_service.create_inline_or_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_needs_input_rejects_wrong_source_task(monkeypatch) -> None:
    """A waiting session linked to an unrelated AgentRun cannot be continued."""
    monkeypatch.setattr(
        generation_module.session_store,
        "get",
        AsyncMock(return_value=SimpleNamespace(status="awaiting_input", questions=["q"], agent_run_id="run-1")),
    )
    run_service = AsyncMock()
    run_service.get.return_value = SimpleNamespace(task_type="interview_report")

    with pytest.raises(ResumeGenerationConflict):
        await ResumeGenerationUseCases()._validate_answer_submission(
            request=SimpleNamespace(session_id="session-1", answers={"q": "a"}),
            user_id="owner",
            run_service=run_service,
        )

@pytest.mark.asyncio
async def test_application_resume_unlink_clears_without_resume_lookup(monkeypatch) -> None:
    """Explicit unlinking clears both current and historical references without a model call."""
    generation_repo = AsyncMock()
    monkeypatch.setattr(application_module, "get_generation_repo", lambda: generation_repo)
    monkeypatch.setattr(
        application_module.job_application_repo,
        "get_application",
        AsyncMock(return_value=_application(generated_resume_id=7, custom_resume_id=6)),
    )
    write = AsyncMock(return_value=_application())
    monkeypatch.setattr(application_module.job_application_repo, "set_linked_resume", write)

    response = await ApplicationUseCases().set_application_resume(
        application_id=1,
        user_id="owner",
        request=ApplicationResumeLinkRequest(resume_id=None),
    )

    assert response.application.linked_resume is None
    generation_repo.get_generated_resume.assert_not_awaited()
    write.assert_awaited_with(application_id=1, user_id="owner", resume_id=None)


@pytest.mark.asyncio
async def test_application_history_reference_is_hidden_when_asset_is_not_owner_visible(monkeypatch) -> None:
    """An invalid historical custom_resume_id remains unreadable instead of leaking metadata."""
    generation_repo = AsyncMock()
    generation_repo.get_generated_resume.return_value = None
    monkeypatch.setattr(application_module, "get_generation_repo", lambda: generation_repo)
    monkeypatch.setattr(
        application_module.job_application_repo,
        "get_application",
        AsyncMock(return_value=_application(custom_resume_id=88)),
    )

    response = await ApplicationUseCases().get_application(application_id=1, user_id="owner")

    assert response.application.linked_resume is None
    generation_repo.get_generated_resume.assert_awaited_with(88, "owner")


@pytest.mark.asyncio
async def test_needs_input_accepts_complete_answers_for_owner_waiting_session(monkeypatch) -> None:
    """A valid waiting session passes governance without creating work inside validation."""
    monkeypatch.setattr(
        generation_module.session_store,
        "get",
        AsyncMock(return_value=SimpleNamespace(status="awaiting_input", questions=["q1", "q2"], agent_run_id=None)),
    )
    run_service = AsyncMock()

    await ResumeGenerationUseCases()._validate_answer_submission(
        request=SimpleNamespace(session_id="session-1", answers={"q1": "a1", "q2": "a2"}),
        user_id="owner",
        run_service=run_service,
    )

    run_service.create_inline_or_get.assert_not_awaited()


def test_ability_profile_progress_uses_effective_company_series_rounds() -> None:
    rows = [
        {
            "status": "completed",
            "series_id": "series-1",
            "round_index": 1,
            "candidate_profile": {"generation_mode": "degraded_evidence_only"},
            "company_profile": None,
            "updated_at": "2026-08-18T10:00:00",
        },
        {
            "status": "completed",
            "series_id": "series-1",
            "round_index": 2,
            "candidate_profile": {"generation_mode": "degraded_evidence_only"},
            "company_profile": None,
            "updated_at": "2026-08-18T11:00:00",
        },
        {
            "status": "completed",
            "series_id": "series-1",
            "round_index": 3,
            "candidate_profile": {"generation_mode": "model_reviewed"},
            "company_profile": None,
            "updated_at": "2026-08-19T10:00:00",
        },
        *[
            {
                "status": "completed",
                "series_id": None,
                "round_index": 1,
                "candidate_profile": {"generation_mode": "model_reviewed"},
                "company_profile": None,
                "updated_at": f"2026-08-{day:02d}T10:00:00",
            }
            for day in range(20, 24)
        ],
    ]

    progress = build_ability_profile_progress(rows)

    assert progress == {
        "completed_rounds": 7,
        "eligible_rounds": 1,
        "required_rounds": 3,
        "remaining_rounds": 2,
        "company_profile_count": 0,
        "degraded_round_indexes": [1, 2],
        "ready_to_generate": False,
        "blocker": "degraded_round_reports",
    }


def test_ability_profile_progress_is_ready_only_with_company_profile() -> None:
    rows = [
        {
            "status": "completed",
            "series_id": "series-ready",
            "round_index": index,
            "candidate_profile": {"generation_mode": "model_reviewed"},
            "company_profile": {"profile": {"overall_assessment": "ready"}} if index == 3 else None,
            "updated_at": f"2026-08-2{index}T10:00:00",
        }
        for index in (1, 2, 3)
    ]

    progress = build_ability_profile_progress(rows)

    assert progress["eligible_rounds"] == 3
    assert progress["company_profile_count"] == 1
    assert progress["remaining_rounds"] == 0
    assert progress["ready_to_generate"] is True
    assert progress["blocker"] == "none"
