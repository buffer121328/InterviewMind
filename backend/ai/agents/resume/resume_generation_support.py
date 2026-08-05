"""Shared bounded-context helpers for the resume generation and adversarial review nodes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ai.runtime.authoritative_context import assemble_authoritative_context
from ai.runtime.context_assembler import ContextAssembler, ContextSource
from ai.runtime.deadlines import TaskDeadline, get_current_task_deadline


@dataclass(frozen=True, slots=True)
class GenerationStageContext:
    """Store per-source bounded text plus safe aggregate audit metadata."""

    values: dict[str, str]
    call_metadata: dict[str, Any]


def bounded_generation_sources(
    *,
    stage: str,
    sources: list[tuple[str, Any, int, str]],
) -> GenerationStageContext:
    """Bound every source independently without exposing source plaintext in audit metadata."""
    values: dict[str, str] = {}
    source_breakdown: dict[str, int] = {}
    truncated_sources: list[str] = []
    fingerprints: list[str] = []

    authoritative_fingerprints: dict[str, str] = {}
    for name, content, max_chars, strategy in sources:
        if strategy == "authoritative":
            authoritative = assemble_authoritative_context(
                agent_name="resume_generator",
                sources={name: content},
            )
            prefix = f"【{name}】\n"
            value = authoritative.model_context
            values[name] = value[len(prefix):] if value.startswith(prefix) else value
            source_breakdown[name] = authoritative.metadata["source_breakdown"][name]
            fingerprint = authoritative.metadata["source_fingerprints"][name]
            authoritative_fingerprints[name] = fingerprint
            fingerprints.append(fingerprint)
            continue
        assembled = ContextAssembler(
            agent_name="resume_generator",
            total_model_chars=max_chars,
            source_budgets={name: max_chars},
        ).assemble([
            ContextSource(
                name=name,
                content=content,
                trusted=True,
                required=True,
                priority=100,
                max_chars=max_chars,
                truncation_strategy=strategy,  # type: ignore[arg-type]
            )
        ])
        prefix = f"【{name}】\n"
        value = assembled.model_context
        if value.startswith(prefix):
            value = value[len(prefix):]
        values[name] = value
        source_breakdown[name] = assembled.input_chars
        fingerprints.append(assembled.content_fingerprint)
        truncated_sources.extend(assembled.truncated_sources)

    return GenerationStageContext(
        values=values,
        call_metadata={
            "stage": stage,
            "input_fingerprint": sha256("|".join(fingerprints).encode("utf-8")).hexdigest(),
            "source_breakdown": source_breakdown,
            "truncated_sources": sorted(set(truncated_sources)),
            "authoritative_source_truncated": False,
            "authoritative_source_fingerprints": authoritative_fingerprints,
            "overflow_strategy": "lossless_segments_or_derived_ir",
        },
    )


def compact_optimization_result(value: dict[str, Any]) -> dict[str, Any]:
    """Select only generation-relevant optimizer fields and cap untrusted list sizes."""
    keyword_analysis = get_keyword_analysis(value)
    return {
        "key_improvements": list(value.get("key_improvements") or [])[:8],
        "keyword_analysis": {
            "jd_keywords": list(keyword_analysis.get("jd_keywords") or [])[:10],
            "missing": list(keyword_analysis.get("missing") or [])[:8],
            "recommendations": list(keyword_analysis.get("recommendations") or [])[:8],
        },
        "change_items": list(value.get("change_items") or [])[:8],
    }


def safe_json_mapping(value: str) -> dict[str, Any]:
    """Decode bounded structured context and degrade to an empty mapping after clipping."""
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def current_generation_deadline() -> TaskDeadline | None:
    """Return the shared resume-generation deadline bound by the session runner."""
    return get_current_task_deadline()


def get_keyword_analysis(optimization_result: dict[str, Any]) -> dict[str, Any]:
    """Normalize optional legacy keyword analysis into a stable mapping."""
    value = optimization_result.get("keyword_analysis")
    return value if isinstance(value, dict) else {}
