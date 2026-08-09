"""Question bank import domain rules."""

from __future__ import annotations

import hashlib
import re

QUESTION_PRIORITY_ORDER = ("required", "high", "low")
QUESTION_TYPES_BY_ROUND: dict[str, tuple[str, ...]] = {
    "tech_initial": ("intro", "tech", "behavior", "system_design"),
    "tech_deep": ("tech", "system_design"),
    "hr_comprehensive": ("intro", "behavior"),
    "voice_default": ("intro", "tech", "behavior", "system_design"),
}


def question_types_for_round(round_type: str) -> tuple[str, ...]:
    """Return question types compatible with an interview round."""
    return QUESTION_TYPES_BY_ROUND.get(round_type, QUESTION_TYPES_BY_ROUND["tech_initial"])


def normalize_question_key(question_text: str) -> str:
    """Normalize question text for owner-scoped duplicate detection."""
    return re.sub(r"[\W_]+", "", question_text.casefold(), flags=re.UNICODE)


def normalize_import_filename(filename: str | None) -> str:
    """Return a bounded import filename for source tracking."""
    return (filename or "questions").strip()[:255] or "questions"


def question_file_source_id(*, user_id: str, filename: str, content: str) -> str:
    """Build a deterministic source id for previewed question-file content."""
    raw = f"{user_id}\0{filename}\0{content}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]
