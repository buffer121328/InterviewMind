"""Perspective-specific reviewer context and dynamic reviewer selection policies."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

PERSPECTIVES = ("technical_depth", "communication", "job_fit", "factual_risk")


def _items(evidence: Iterable[Any]) -> list[dict[str, Any]]:
    """Normalize Pydantic or mapping evidence items without mutating caller data."""
    normalized = []
    for item in evidence:
        if hasattr(item, "model_dump"):
            normalized.append(item.model_dump())
        elif isinstance(item, Mapping):
            normalized.append(dict(item))
    return normalized


def build_reviewer_contexts(
    *,
    resume: str,
    job_description: str,
    company_info: str,
    evidence: Iterable[Any],
) -> dict[str, str]:
    """Build distinct, evidence-bound context views for each report reviewer."""
    rows = _items(evidence)
    def project(*keys: str) -> list[dict[str, Any]]:
        """Project evidence to the fields needed by one reviewer while retaining Q ids."""
        return [
            {key: row.get(key) for key in ("question_id", *keys) if row.get(key) not in (None, [], "")}
            for row in rows
        ]
    return {
        "technical_depth": json.dumps({
            "resume": resume,
            "job_description": job_description,
            "evidence": project("question_summary", "candidate_claims", "demonstrated_skills", "score_or_signal"),
        }, ensure_ascii=False),
        "communication": json.dumps({
            "evidence": project("question_summary", "communication_observations", "candidate_claims"),
        }, ensure_ascii=False),
        "job_fit": json.dumps({
            "job_description": job_description,
            "company_info": company_info,
            "resume": resume,
            "evidence": project("demonstrated_skills", "candidate_claims"),
        }, ensure_ascii=False),
        "factual_risk": json.dumps({
            "resume": resume,
            "evidence": project("candidate_claims", "missing_evidence", "question_summary"),
        }, ensure_ascii=False),
    }


def select_ability_reviewers(profiles: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """Select the minimum sufficient reviewers from persisted profile evidence coverage."""
    rows = [dict(item) for item in profiles]
    if not rows:
        return ()
    selected: list[str] = []
    if any(row.get("professional_competence") or row.get("logic_problem_solving") for row in rows):
        selected.append("technical_depth")
    if any(row.get("communication") or row.get("collaboration") for row in rows):
        selected.append("communication")
    if any(row.get("recommendation") or row.get("job_description") or row.get("company_info") for row in rows):
        selected.append("job_fit")
    if len(rows) > 1 or any(row.get("confidence") is not None for row in rows):
        selected.append("factual_risk")
    return tuple(selected or ("technical_depth", "factual_risk"))
