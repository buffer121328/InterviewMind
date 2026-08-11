"""UTC clock regression tests for persistence and API timestamps."""

from datetime import UTC, datetime


def test_utc_now_uses_utc_even_when_local_calendar_day_is_later(monkeypatch):
    """A host in UTC+8 must not persist the next local calendar day as UTC."""
    from app import clock

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return cls(2026, 8, 4, 16, 30, tzinfo=UTC)

    monkeypatch.setattr(clock, "datetime", FixedDateTime)

    assert clock.utc_now() == datetime(2026, 8, 4, 16, 30)
    assert clock.utc_now().tzinfo is None


def test_interview_report_profile_uses_project_utc_clock(monkeypatch):
    """Interview report profiles must not use the host's local calendar date."""
    from ai.workflows.analysis import analysis_service
    from app.schemas.llm_outputs import CandidateProfileOutput

    fixed_now = datetime(2026, 8, 4, 18, 45, 0)
    monkeypatch.setattr(analysis_service, "utc_now", lambda: fixed_now)
    dimension = {
        "score": 7.0,
        "evidence": "一组真实问答证据",
        "reason": "证据有限",
    }
    result = CandidateProfileOutput.model_validate({
        "professional_competence": dimension,
        "execution_results": dimension,
        "logic_problem_solving": dimension,
        "communication": dimension,
        "growth_potential": dimension,
        "collaboration": dimension,
        "skill_tags": ["Agent"],
    })

    profile = analysis_service.SessionReportAnalysisService._to_candidate_profile(
        result,
        total_questions=1,
    )

    assert profile.last_updated == "2026-08-04T18:45:00"


def test_empty_ability_profile_uses_project_utc_clock(monkeypatch):
    """Empty ability profiles must use the same project UTC clock."""
    from ai.workflows.analysis import ability_service

    fixed_now = datetime(2026, 8, 4, 18, 46, 0)
    monkeypatch.setattr(ability_service, "utc_now", lambda: fixed_now)

    profile = ability_service.AbilityAnalysisService()._get_empty_profile()

    assert profile.last_updated == "2026-08-04T18:46:00"
