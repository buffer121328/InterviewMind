"""Shared UTC clock helpers for naive database timestamp columns."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC instant as a naive datetime for legacy DB columns."""
    return datetime.now(UTC).replace(tzinfo=None)
