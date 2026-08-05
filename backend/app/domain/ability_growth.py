"""Deterministic mapping for the owner-scoped ability growth record."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

DIMENSION_KEYS = (
    "professional_competence",
    "execution_results",
    "logic_problem_solving",
    "communication",
    "growth_potential",
    "collaboration",
)


def _record(value: object) -> dict[str, Any]:
    """Return a shallow dictionary for mapping-like persisted JSON values."""
    return dict(value) if isinstance(value, Mapping) else {}


def _score(profile: Mapping[str, Any], key: str) -> float | None:
    """Read one finite numeric dimension score without inventing missing values."""
    value = _record(profile.get(key)).get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_ability_growth_record(
    *,
    overall: Mapping[str, Any],
    source_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build source history and latest dimension deltas from persisted profiles only.

    Source rows must already be owner-scoped by the repository. The function performs
    no model calls and omits deltas when either of the two newest profiles lacks a score.
    """
    sources: list[dict[str, Any]] = []
    for row in source_rows:
        payload = _record(row.get("company_profile"))
        profile = _record(payload.get("profile"))
        if not profile:
            continue
        sources.append(
            {
                "session_id": str(row.get("session_id") or ""),
                "series_id": str(row.get("series_id") or "") or None,
                "title": str(row.get("title") or row.get("company_info") or row.get("series_id") or "历史面试"),
                "completed_at": str(row.get("updated_at") or ""),
                "profile": profile,
            }
        )

    changes: dict[str, float] = {}
    if len(sources) >= 2:
        latest = sources[0]["profile"]
        previous = sources[1]["profile"]
        for key in DIMENSION_KEYS:
            latest_score = _score(latest, key)
            previous_score = _score(previous, key)
            if latest_score is not None and previous_score is not None:
                changes[key] = round(latest_score - previous_score, 2)

    return {
        "success": True,
        "profile": _record(overall.get("profile")),
        "generated_at": overall.get("updated_at"),
        "sample_count": len(sources),
        "sources": sources,
        "dimension_changes": changes,
    }
