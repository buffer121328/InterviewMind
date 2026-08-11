"""提供评审上下文相关后端功能。"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

PERSPECTIVES = ("technical_depth", "communication", "job_fit", "factual_risk")


def _items(evidence: Iterable[Any]) -> list[dict[str, Any]]:
    """处理条目相关后端逻辑。"""
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
    answer_points_by_question: Mapping[str, list[str]] | None = None,
) -> dict[str, str]:
    """构建评审上下文相关后端逻辑。"""
    rows = _items(evidence)
    standards = {
        str(key): [str(point) for point in value if str(point).strip()]
        for key, value in (answer_points_by_question or {}).items()
        if value
    }

    def project(*keys: str, include_points: bool = False) -> list[dict[str, Any]]:
        """处理项目相关后端逻辑。"""
        return [
            {
                **{key: row.get(key) for key in ("question_id", *keys) if row.get(key) not in (None, [], "")},
                **({"answer_points": standards.get(str(row.get("question_id")))}
                   if include_points and standards.get(str(row.get("question_id"))) else {}),
            }
            for row in rows
        ]
    return {
        "technical_depth": json.dumps({
            "resume": resume,
            "job_description": job_description,
            "evidence": project(
                "question_summary", "candidate_claims", "demonstrated_skills", "score_or_signal",
                include_points=True,
            ),
        }, ensure_ascii=False),
        "communication": json.dumps({
            "evidence": project("question_summary", "communication_observations", "candidate_claims"),
        }, ensure_ascii=False),
        "job_fit": json.dumps({
            "job_description": job_description,
            "company_info": company_info,
            "resume": resume,
            "evidence": project("demonstrated_skills", "candidate_claims", include_points=True),
        }, ensure_ascii=False),
        "factual_risk": json.dumps({
            "resume": resume,
            "evidence": project("candidate_claims", "missing_evidence", "question_summary"),
        }, ensure_ascii=False),
    }


def select_ability_reviewers(profiles: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """选择能力评审相关后端逻辑。"""
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
