"""Versioned, auditable interview-turn context contracts.

This module deliberately keeps authoritative source text out of persistence and
observability payloads. The model receives a deterministic stable prefix plus
one dynamic suffix; the database retains only source fingerprints and message
references needed to reconstruct a decision from the authoritative session.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

STABLE_CONTEXT_SCHEMA_VERSION = "interview-stable-context.v1"
TURN_STATE_SCHEMA_VERSION = "interview-turn-state.v1"

_DYNAMIC_PREFIX_EXCLUSIONS = frozenset({
    "run_id", "timestamp", "current_answer", "answer", "follow_up_count",
    "total_follow_up_count", "tool_results", "current_question_index", "current_sub_question",
})


def _normalise_json(value: Any) -> Any:
    """Return a deterministic JSON-compatible value without mutating caller data."""
    if isinstance(value, Mapping):
        return {str(key): _normalise_json(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalise_json(item) for item in value]
    if isinstance(value, set):
        return sorted((_normalise_json(item) for item in value), key=canonical_json)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    """Serialize a value using the stable format used for fingerprints."""
    return json.dumps(_normalise_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    """Build a SHA-256 fingerprint from canonical serialized content."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _source_descriptor(kind: str, content: str) -> dict[str, Any]:
    """Return auditable source metadata without exposing source text in events."""
    return {"kind": kind, "fingerprint": sha256(content.encode("utf-8")).hexdigest(), "char_count": len(content)}


def _normalise_plan(plan: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Keep final question-plan fields in deterministic question order."""
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(plan or [], start=1):
        normalized.append({
            "id": item.get("id", index),
            "topic": str(item.get("topic") or ""),
            "content": str(item.get("content") or ""),
            "type": str(item.get("type") or ""),
            "hint": str(item.get("hint") or ""),
            "answer_points": _normalise_json(item.get("answer_points") or []),
            "followups": _normalise_json(item.get("followups") or []),
            "sources": _normalise_json(item.get("sources") or []),
        })
    return normalized


@dataclass(frozen=True, slots=True)
class StableInterviewContext:
    """A finalized stable prefix and its safe observability metadata."""

    schema_version: str
    payload: dict[str, Any]
    canonical: str
    fingerprint: str

    def model_event_fields(self) -> dict[str, Any]:
        """Expose only safe cache-attribution fields for model events."""
        return {
            "prompt_prefix_version": self.schema_version,
            "prompt_prefix_fingerprint": self.fingerprint,
            "stable_input_chars": len(self.canonical),
        }

    def as_system_message(self) -> str:
        """Render the immutable prefix as one deterministic system block."""
        return f"【稳定面试上下文 {self.schema_version}】\n{self.canonical}"


def build_stable_context(
    *,
    resume_context: str | None,
    job_description: str | None,
    company_info: str | None,
    interview_plan: Sequence[Mapping[str, Any]] | None,
    round_index: int,
    round_type: str,
    memory_context: str | None,
    rubric: Mapping[str, Any] | None,
    prompt_version: str,
    round_strategy_version: str,
    dynamic_fields: Mapping[str, Any] | None = None,
) -> StableInterviewContext:
    """Build a stable prefix from only finalized, cache-safe interview inputs.

    ``dynamic_fields`` is accepted to make misuse explicit but is never merged
    into the payload. This makes accidental inclusion of run-time-only data
    testable and prevents cache eligibility from depending on mutable state.
    """
    _ = {key: value for key, value in (dynamic_fields or {}).items() if key in _DYNAMIC_PREFIX_EXCLUSIONS}
    resume = str(resume_context or "")
    jd = str(job_description or "")
    company = str(company_info or "")
    memory = str(memory_context or "")
    payload = {
        "schema_version": STABLE_CONTEXT_SCHEMA_VERSION,
        "prompt_version": str(prompt_version),
        "round_strategy_version": str(round_strategy_version),
        "round": {"index": int(round_index), "type": str(round_type)},
        "sources": {
            "resume": {**_source_descriptor("resume", resume), "content": resume},
            "job_description": {**_source_descriptor("job_description", jd), "content": jd},
            "company_info": {**_source_descriptor("company_info", company), "content": company},
            "frozen_memory": {**_source_descriptor("frozen_memory", memory), "content": memory},
        },
        "question_plan": _normalise_plan(interview_plan),
        "rubric": _normalise_json(rubric or {}),
    }
    canonical = canonical_json(payload)
    return StableInterviewContext(
        schema_version=STABLE_CONTEXT_SCHEMA_VERSION,
        payload=_normalise_json(payload),
        canonical=canonical,
        fingerprint=sha256(canonical.encode("utf-8")).hexdigest(),
    )


def stable_context_from_payload(payload: Mapping[str, Any]) -> StableInterviewContext:
    """Rehydrate a private persisted stable snapshot without accepting a stale fingerprint."""
    normalized = _normalise_json(payload)
    canonical = canonical_json(normalized)
    return StableInterviewContext(
        schema_version=str(normalized.get("schema_version") or STABLE_CONTEXT_SCHEMA_VERSION),
        payload=normalized,
        canonical=canonical,
        fingerprint=sha256(canonical.encode("utf-8")).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class DynamicInterviewSuffix:
    """Current-turn input, complete source representation, and safe audit data."""

    payload: dict[str, Any]
    answer_representation: dict[str, Any]
    audit: dict[str, Any]

    def as_user_message(self) -> str:
        """Render dynamic input after the stable system prefix."""
        return "【当前面试回合动态上下文】\n" + canonical_json(self.payload)

    def model_event_fields(self) -> dict[str, Any]:
        """Return dynamic-size and source-reference metadata without raw text."""
        return {"dynamic_input_chars": len(canonical_json(self.payload)), "dynamic_source_audit": dict(self.audit)}


def _complete_source_chunks(content: str, max_chunk_chars: int) -> list[dict[str, Any]]:
    """Split a source without losing characters or relying on head/tail clipping."""
    if max_chunk_chars <= 0:
        raise ValueError("max_chunk_chars must be positive")
    parts = [content[index:index + max_chunk_chars] for index in range(0, len(content), max_chunk_chars)] or [""]
    return [
        {
            "index": index,
            "total": len(parts),
            "content": part,
            "fingerprint": sha256(part.encode("utf-8")).hexdigest(),
            "char_count": len(part),
        }
        for index, part in enumerate(parts, start=1)
    ]


def build_dynamic_suffix(
    *,
    current_question: str,
    current_answer: str,
    turn_state: Mapping[str, Any] | None,
    tool_results: Mapping[str, Any] | None,
    max_chunk_chars: int = 4_000,
) -> DynamicInterviewSuffix:
    """Build the non-cacheable current-turn block with a complete answer source."""
    answer = str(current_answer or "")
    answer_representation = {"source": _source_descriptor("current_answer", answer), "chunks": _complete_source_chunks(answer, max_chunk_chars)}
    payload = {
        "current_question": str(current_question or ""),
        "current_answer": answer_representation,
        "turn_state": _normalise_json(turn_state or {}),
        "tool_results": _normalise_json(tool_results or {}),
    }
    audit = {
        "answer_fingerprint": answer_representation["source"]["fingerprint"],
        "answer_char_count": answer_representation["source"]["char_count"],
        "answer_chunk_count": len(answer_representation["chunks"]),
        "has_tool_results": bool(tool_results),
    }
    return DynamicInterviewSuffix(payload=_normalise_json(payload), answer_representation=_normalise_json(answer_representation), audit=audit)


def _reference_list(value: Sequence[Any] | None) -> list[str]:
    """Normalize source references without resolving or logging their contents."""
    return [str(item) for item in (value or []) if str(item).strip()]


def _state_items(value: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize state evidence items while retaining only structured fields."""
    return [_normalise_json(item) for item in (value or [])]


def build_turn_state(
    *,
    current_question_index: int,
    current_question_id: str | None,
    stable_prefix_fingerprint: str,
    round_strategy_version: str,
    covered_dimensions: Sequence[Mapping[str, Any]] | None = None,
    evidence_summaries: Sequence[Mapping[str, Any]] | None = None,
    unresolved_gaps: Sequence[Mapping[str, Any]] | None = None,
    claims_to_verify: Sequence[Mapping[str, Any]] | None = None,
    follow_up_count: int = 0,
    total_follow_up_count: int = 0,
    max_follow_ups: int = 2,
    max_total_follow_ups: int = 0,
    current_sub_question: str | None = None,
    last_action: str | None = None,
    last_transition: str | None = None,
    source_message_refs: Sequence[Any] | None = None,
    source_message_version: int = 0,
    state_version: int = 1,
) -> dict[str, Any]:
    """Create the persisted state shape used to recover a later interview turn."""
    return {
        "schema_version": TURN_STATE_SCHEMA_VERSION,
        "state_version": max(1, int(state_version)),
        "source_message_version": max(0, int(source_message_version)),
        "stable_prefix_fingerprint": str(stable_prefix_fingerprint),
        "round_strategy_version": str(round_strategy_version),
        "current_question_index": max(0, int(current_question_index)),
        "current_question_id": str(current_question_id or ""),
        "current_sub_question": str(current_sub_question or "") or None,
        "covered_dimensions": _state_items(covered_dimensions),
        "evidence_summaries": _state_items(evidence_summaries),
        "unresolved_gaps": _state_items(unresolved_gaps),
        "claims_to_verify": _state_items(claims_to_verify),
        "follow_up_count": max(0, int(follow_up_count)),
        "total_follow_up_count": max(0, int(total_follow_up_count)),
        "max_follow_ups": max(0, int(max_follow_ups)),
        "max_total_follow_ups": max(0, int(max_total_follow_ups)),
        "last_action": str(last_action or ""),
        "last_transition": str(last_transition or ""),
        "source_message_refs": _reference_list(source_message_refs),
    }


def advance_turn_state(
    previous: Mapping[str, Any] | None,
    *,
    current_question_index: int,
    current_question_id: str | None,
    follow_up_count: int,
    total_follow_up_count: int,
    last_action: str,
    last_transition: str,
    source_message_refs: Sequence[Any],
    current_sub_question: str | None = None,
    source_message_version: int | None = None,
) -> dict[str, Any]:
    """Advance an existing state once; source text remains in authoritative messages."""
    prior = dict(previous or {})
    return build_turn_state(
        current_question_index=current_question_index,
        current_question_id=current_question_id,
        stable_prefix_fingerprint=str(prior.get("stable_prefix_fingerprint") or ""),
        round_strategy_version=str(prior.get("round_strategy_version") or ""),
        covered_dimensions=prior.get("covered_dimensions"),
        evidence_summaries=prior.get("evidence_summaries"),
        unresolved_gaps=prior.get("unresolved_gaps"),
        claims_to_verify=prior.get("claims_to_verify"),
        follow_up_count=follow_up_count,
        total_follow_up_count=total_follow_up_count,
        max_follow_ups=int(prior.get("max_follow_ups") or 0),
        max_total_follow_ups=int(prior.get("max_total_follow_ups") or 0),
        current_sub_question=current_sub_question,
        last_action=last_action,
        last_transition=last_transition,
        source_message_refs=source_message_refs,
        source_message_version=(int(source_message_version) if source_message_version is not None else int(prior.get("source_message_version") or 0)),
        state_version=int(prior.get("state_version") or 0) + 1,
    )
