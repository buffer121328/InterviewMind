"""Regression tests for stable interview-session display titles."""

from datetime import datetime

from app.domain.interview_session_titles import build_interview_session_title


def test_interview_session_title_contains_time_type_question_count_and_round():
    """A generated title exposes the key facts requested by the session sidebar."""
    title = build_interview_session_title(
        started_at=datetime(2026, 7, 28, 14, 5),
        round_type="tech_deep",
        max_questions=12,
        round_index=2,
    )

    assert title == "2026-07-28 14:05 · 深度技术面 · 12题 · 第2轮"
