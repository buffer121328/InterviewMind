"""Interview-session title formatting rules shared by creation workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Final

from app.domain.interview_rounds import resolve_max_questions, resolve_round_type


ROUND_TYPE_LABELS: Final[dict[str, str]] = {
    "tech_initial": "综合面",
    "tech_deep": "深度技术面",
    "hr_comprehensive": "HR 综合面",
}


def build_interview_session_title(
    *,
    started_at: datetime,
    round_type: str | None,
    max_questions: int | None,
    round_index: int = 1,
) -> str:
    """Build a concise local-time title containing time, interview type, round, and question count."""
    resolved_round_type = resolve_round_type(round_type, round_index=round_index)
    resolved_questions = resolve_max_questions(
        resolved_round_type,
        max_questions,
        round_index=round_index,
    )
    timestamp = started_at.strftime("%Y-%m-%d %H:%M")
    return (
        f"{timestamp} · {ROUND_TYPE_LABELS[resolved_round_type]}"
        f" · {resolved_questions}题 · 第{max(1, round_index)}轮"
    )
