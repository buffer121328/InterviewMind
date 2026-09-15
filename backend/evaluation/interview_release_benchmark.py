"""Deterministic structural release benchmark for interview-context changes.

This benchmark deliberately does not call a provider.  It validates release
contracts that can be reproduced offline and separately reports the telemetry
dimensions that require a preserved historical snapshot and configured model
credentials.  It must not be presented as an observed provider-cost result.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from ai.agents.interview.turn_context import build_stable_context
from ai.runtime.models.prompt_cache import prepare_stable_prompt_cache
from ai.workflows.analysis.reviewers.multi_reviewer import _REVIEWERS
from app.domain.agent_runs import (
    TASK_TYPE_INTERVIEW_REPORT,
    TASK_TYPE_INTERVIEW_START,
    TASK_TYPE_INTERVIEW_TURN,
    TASK_TYPE_VOICE_INTERVIEW_TURN,
)
from app.domain.interview_round_strategy import (
    repair_round_plan,
    round_question_type_distribution,
    validate_round_plan,
)

_DATASET_PATH = Path(__file__).with_name("datasets") / "interview_golden.json"
_TELEMETRY_UNAVAILABLE_REASON = (
    "No persisted pre-change provider telemetry snapshot or explicitly configured "
    "evaluation-model credential is available in this workspace."
)


class _CacheCapableModel:
    """Minimal native-cache capability stub; no network client is created."""

    _prompt_cache_capability = "anthropic_ephemeral"


def _dataset_cases(dataset_path: Path) -> list[dict[str, Any]]:
    """Load the versioned golden cases while rejecting malformed local data."""

    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("interview golden dataset must be a JSON list")
    cases: list[dict[str, Any]] = []
    for case in raw:
        if not isinstance(case, dict):
            raise ValueError("interview golden dataset entries must be JSON objects")
        cases.append(case)
    return cases


def _question_plan(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Copy one case's expected questions into the runtime planner input shape."""

    questions = case.get("expected_questions")
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes, bytearray)):
        raise ValueError(f"case {case.get('id', '<unknown>')} has no question sequence")
    if not all(isinstance(question, Mapping) for question in questions):
        raise ValueError(f"case {case.get('id', '<unknown>')} has a non-object question")
    return [dict(question) for question in questions]


def _round_policy_summary(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Replay every golden plan through the shared runtime policy repair/validator."""

    results: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id") or "")
        round_type = str(case.get("round_type") or "")
        max_questions = int(case.get("max_questions") or 0)
        expected_count = int(case.get("expected_question_count") or max_questions)
        repaired = repair_round_plan(
            _question_plan(case),
            round_type=round_type,
            max_questions=max_questions,
        )
        violations = validate_round_plan(
            repaired,
            round_type=round_type,
            expected_count=expected_count,
        )
        results.append(
            {
                "case_id": case_id,
                "round_type": round_type,
                "question_count": len(repaired),
                "distribution": round_question_type_distribution(repaired),
                "violations": violations,
                "compliant": not violations,
            }
        )
    return {
        "golden_case_count": len(results),
        "compliant_case_count": sum(1 for result in results if result["compliant"]),
        "cases": results,
    }


def _prompt_cache_summary(case: Mapping[str, Any]) -> dict[str, Any]:
    """Verify an eligible stable prefix is capability-gated without a provider call."""

    stable_context = build_stable_context(
        resume_context=str(case.get("resume") or ""),
        job_description=str(case.get("job_description") or ""),
        company_info=str(case.get("company_info") or ""),
        interview_plan=_question_plan(case),
        round_index=1,
        round_type=str(case.get("round_type") or ""),
        memory_context="",
        rubric={"evaluation": "golden-release-benchmark"},
        prompt_version="release-benchmark.v1",
        round_strategy_version="interview-round-policy.v1",
        dynamic_fields={"current_answer": "must not enter stable prefix"},
    )
    dynamic_input = "deterministic current-answer representation"
    metadata = {
        **stable_context.model_event_fields(),
        "dynamic_input_chars": len(dynamic_input),
        "prompt_cache_eligible": True,
        "prompt_cache_stable_message_index": 0,
    }
    messages = [
        {"role": "system", "content": stable_context.as_system_message()},
        {"role": "user", "content": dynamic_input},
    ]
    capable = prepare_stable_prompt_cache(messages, llm=_CacheCapableModel(), metadata=metadata)
    unsupported = prepare_stable_prompt_cache(messages, llm=object(), metadata=metadata)
    return {
        "before": {
            "stable_prefix_contract": False,
            "provider_cache_eligibility": False,
        },
        "after": {
            "stable_prefix_contract": True,
            "prompt_prefix_version": stable_context.schema_version,
            "prompt_prefix_fingerprint_present": bool(stable_context.fingerprint),
            "stable_input_chars": len(stable_context.canonical),
            "dynamic_input_chars": len(dynamic_input),
            "cache_eligible": capable.event_fields["prompt_cache_eligible"],
            "capable_provider_control_applied": capable.applied,
            "unsupported_provider_control_applied": unsupported.applied,
            "unsupported_provider_status": unsupported.event_fields["prompt_cache_status"],
        },
        "observed_cache_read_tokens": {
            "status": "not_measured",
            "reason": _TELEMETRY_UNAVAILABLE_REASON,
        },
    }


def build_interview_release_benchmark(dataset_path: Path | None = None) -> dict[str, Any]:
    """Build a JSON-safe offline comparison for the interview release contract.

    The ``before`` side contains only stable architectural facts retained by the
    change proposal. Provider-dependent fields remain explicitly unmeasured
    rather than estimated from character counts or retry configuration.
    """

    resolved_path = dataset_path or _DATASET_PATH
    cases = _dataset_cases(resolved_path)
    if not cases:
        raise ValueError("interview golden dataset must contain at least one case")
    round_policy = _round_policy_summary(cases)
    deep_logical_calls = len(_REVIEWERS) + 1  # four reviewers plus one narrative composer
    return {
        "benchmark": "interview-context-report-modes.structural.v1",
        "measurement_scope": "offline_deterministic_structural_contracts",
        "dataset": {
            "file": resolved_path.name,
            "sha256": sha256(resolved_path.read_bytes()).hexdigest(),
            "case_count": len(cases),
        },
        "round_type_compliance": {
            "before": {
                "shared_runtime_policy": False,
                "observed_dataset_snapshot": "not_available",
            },
            "after": round_policy,
        },
        "agent_run_boundaries": {
            "before": {
                "per_session_start": 1,
                "per_text_answer": 1,
                "per_voice_answer": 1,
                "per_report": 1,
            },
            "after": {
                "per_session_start": 1,
                "per_text_answer": 1,
                "per_voice_answer": 1,
                "per_report": 1,
                "task_types": {
                    "start": TASK_TYPE_INTERVIEW_START,
                    "text_turn": TASK_TYPE_INTERVIEW_TURN,
                    "voice_turn": TASK_TYPE_VOICE_INTERVIEW_TURN,
                    "report": TASK_TYPE_INTERVIEW_REPORT,
                },
            },
        },
        "report_mode_calls": {
            "before": {
                "available_modes": ["deep"],
                "deep_logical_model_calls": deep_logical_calls,
                "standard_logical_model_calls": "not_available",
            },
            "after": {
                "deep_logical_model_calls": deep_logical_calls,
                "standard_logical_model_calls": 1,
                "standard_channel": "smart",
            },
            "physical_attempts": {
                "status": "not_measured",
                "reason": _TELEMETRY_UNAVAILABLE_REASON,
            },
            "provider_cost": {
                "status": "not_measured",
                "reason": _TELEMETRY_UNAVAILABLE_REASON,
            },
        },
        "prompt_cache": _prompt_cache_summary(cases[0]),
        "input_tokens": {
            "status": "not_measured",
            "reason": _TELEMETRY_UNAVAILABLE_REASON,
            "safe_structural_proxy": "stable_input_chars is recorded separately from dynamic_input_chars",
        },
        "provider_telemetry_comparison_complete": False,
    }


def main() -> int:
    """Print the deterministic benchmark in a CI- and review-friendly form."""

    print(json.dumps(build_interview_release_benchmark(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
