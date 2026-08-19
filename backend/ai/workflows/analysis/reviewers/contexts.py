"""提供评审上下文相关后端功能。"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any, Iterable, Mapping

from app.config import get_settings
from observability.events import record_model_event
from observability.usage import measure_model_input

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
    qa_history: Iterable[Mapping[str, Any]] | None = None,
    answer_points_by_question: Mapping[str, list[str]] | None = None,
    monitor_stage: str | None = None,
) -> dict[str, str]:
    """构建评审上下文，并可选记录不含原文的组装体积与耗时事件。"""
    started_at = perf_counter()
    rows = _items(evidence)
    standards = {
        str(key): [str(point) for point in value if str(point).strip()]
        for key, value in (answer_points_by_question or {}).items()
        if value
    }
    complete_qa_history = [
        {
            "question": str(item.get("question") or ""),
            "answer": str(item.get("answer") or ""),
        }
        for item in (qa_history or ())
        if str(item.get("question") or "").strip() or str(item.get("answer") or "").strip()
    ]

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
    context_payloads = {
        "technical_depth": {
            "resume": resume,
            "job_description": job_description,
            "qa_history": complete_qa_history,
            "evidence": project(
                "question_summary", "candidate_claims", "demonstrated_skills", "score_or_signal",
                include_points=True,
            ),
        },
        "communication": {
            "evidence": project("question_summary", "communication_observations", "candidate_claims"),
        },
        "job_fit": {
            "job_description": job_description,
            "company_info": company_info,
            "resume": resume,
            "evidence": project("demonstrated_skills", "candidate_claims"),
        },
        "factual_risk": {
            "resume": resume,
            "evidence": project("candidate_claims", "missing_evidence", "question_summary"),
        },
    }
    contexts = {
        perspective: json.dumps(payload, ensure_ascii=False)
        for perspective, payload in context_payloads.items()
    }
    if monitor_stage:
        chars_per_token = get_settings().llm_estimated_chars_per_token
        duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        for perspective, context in contexts.items():
            source_metrics = {
                name: measure_model_input(value, chars_per_token=chars_per_token)
                for name, value in context_payloads[perspective].items()
            }
            context_metrics = measure_model_input(
                context,
                chars_per_token=chars_per_token,
            )
            context_metrics["source_breakdown"] = {
                name: metrics["input_chars"]
                for name, metrics in source_metrics.items()
            }
            context_metrics["source_token_breakdown"] = {
                name: metrics["estimated_input_tokens"]
                for name, metrics in source_metrics.items()
            }
            record_model_event(
                event_type="context.assembled",
                stage=f"{monitor_stage}.{perspective}",
                status="completed",
                duration_ms=duration_ms,
                **context_metrics,
            )
    return contexts


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
