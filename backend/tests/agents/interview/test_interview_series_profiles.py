from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _profile(score: float, label: str) -> dict:
    dimension = {"score": score, "evidence": label}
    return {
        "professional_competence": dict(dimension),
        "execution_results": dict(dimension),
        "logic_problem_solving": dict(dimension),
        "communication": dict(dimension),
        "growth_potential": dict(dimension),
        "collaboration": dict(dimension),
        "skill_tags": [label],
        "total_questions_analyzed": 5,
        "last_updated": datetime.now().isoformat(),
        "key_strengths": [f"strength-{label}"],
        "key_weaknesses": [f"weakness-{label}"],
    }


def test_round_limit_is_three():
    from app.domain.interview_rounds import MAX_INTERVIEW_ROUNDS, validate_next_round_index

    assert MAX_INTERVIEW_ROUNDS == 3
    assert validate_next_round_index(2) == 2
    assert validate_next_round_index(3) == 3
    with pytest.raises(ValueError, match="最多只能进行 3 轮面试"):
        validate_next_round_index(4)


@pytest.mark.asyncio
async def test_completed_session_rejects_new_message():
    from app.db.repositories.session.repo_impl.message_mgmt import MessageService

    mgmt = AsyncMock()
    mgmt.get_session.return_value = SimpleNamespace(metadata=SimpleNamespace(status="completed"))
    service = MessageService(mgmt)

    with pytest.raises(ValueError, match="面试已完成"):
        await service.add_message("session-1", "user", "late answer", user_id="user-1")


@pytest.mark.asyncio
async def test_company_profile_combines_three_rounds(monkeypatch):
    from ai.workflows.analysis.ability_service import AbilityAnalysisService

    async def no_model(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "ai.workflows.analysis.reviewers.multi_reviewer.run_multi_reviewer_map_reduce",
        no_model,
    )
    result = await AbilityAnalysisService().aggregate_company_profile(
        [_profile(6, "round-1"), _profile(8, "round-2"), _profile(7, "round-3")]
    )

    assert result.total_questions_analyzed == 15
    assert set(result.skill_tags) >= {"round-1", "round-2", "round-3"}
    assert 6 < result.professional_competence.score < 8


def test_recent_company_profile_query_is_scoped_to_completed_third_round():
    from app.db.repositories.session.repo_impl.profile_mgmt import build_recent_company_profiles_stmt

    sql = str(build_recent_company_profiles_stmt(limit=5, user_id="user-1"))
    assert "sessions.company_profile IS NOT NULL" in sql
    assert "sessions.round_index" in sql
    assert "sessions.status" in sql
    assert "sessions.user_id" in sql
    assert "parent_session_id = sessions.session_id" not in sql


@pytest.mark.asyncio
async def test_same_round_cannot_create_duplicate_next_round(monkeypatch):
    """A completed round may own at most one linked next-round session."""
    from app.db.repositories.session.repo_impl import session_advanced as module

    parent = SimpleNamespace(
        metadata=SimpleNamespace(
            status="completed",
            round_index=1,
            series_id="series-1",
            mode="text",
            resume_filename="resume.pdf",
            resume_content="resume",
            job_description="jd",
            company_info="company",
        )
    )
    mgmt = AsyncMock()
    mgmt.get_session.return_value = parent
    service = module.SessionAdvancedService(mgmt)

    locked_parent = MagicMock()
    locked_parent.one_or_none.return_value = ("user-1", "series-1")
    existing_child = MagicMock()
    existing_child.scalar_one_or_none.return_value = "round-2-existing"
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [locked_parent, existing_child]

    class FakeSessionContext:
        """Provide one reusable mocked transaction boundary for the repository test."""

        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(module, "async_session", FakeSessionContext)

    with pytest.raises(ValueError, match="该轮已创建下一轮面试"):
        await service.create_next_round("round-1", user_id="user-1")

    db.add.assert_not_called()
