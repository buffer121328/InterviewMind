"""Question bank import domain rules."""

from __future__ import annotations

import hashlib


def normalize_import_filename(filename: str | None) -> str:
    """Return a bounded import filename for source tracking."""
    return (filename or "questions").strip()[:255] or "questions"


def question_file_source_id(*, user_id: str, filename: str, content: str) -> str:
    """Build a deterministic source id for previewed question-file content."""
    raw = f"{user_id}\0{filename}\0{content}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]
