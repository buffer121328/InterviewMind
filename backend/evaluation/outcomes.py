"""运行成功、语义成功、完全成功与人工复核原因的统一判定。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from evaluation.schemas import (
    AgentEvalRecord,
    EvalApprovalStatus,
    EvalCaseOutcome,
    EvalScore,
    EvalScoreStatus,
    EvalToolEffect,
    EvalToolStatus,
)

_OPERATIONAL_SCORE_PREFIXES = ("runtime.", "observability.", "budget.")
_TOOL_SELECTION_METRICS = frozenset(
    {
        "tool.name_and_key_parameter_accuracy",
        "tool.expected_call_coverage",
        "tool.allowed_call_compliance",
        "tool.key_argument_contract_compliance",
        "tool.fixture_result_adoption",
        "workflow.required_tool_call_coverage",
        "workflow.tool_degradation_compliance",
        "workflow.external_effect_interception",
    }
)


def is_semantic_score(score: EvalScore) -> bool:
    """判断一个非硬门禁 Score 是否直接衡量输出、事实、工具选择或流程语义。"""

    return not score.hard_gate and not score.metric_name.startswith(
        _OPERATIONAL_SCORE_PREFIXES
    )


def semantic_score_average(scores: Sequence[EvalScore]) -> float | None:
    """仅聚合已适用的语义分数，避免运行时可靠性掩盖输出质量。"""

    values = [
        score.value
        for score in scores
        if is_semantic_score(score)
        and score.status is not EvalScoreStatus.NOT_APPLICABLE
        and score.value is not None
    ]
    return sum(values) / len(values) if values else None


def classify_case_outcome(
    record: AgentEvalRecord,
    scores: Sequence[EvalScore],
    *,
    extra_review_reasons: Iterable[str] = (),
) -> EvalCaseOutcome:
    """从本地事实和来源分离分数生成三类成功及稳定人工复核原因。"""

    hard_gate_scores = [score for score in scores if score.hard_gate]
    hard_gate_passed = all(
        score.status is EvalScoreStatus.PASSED for score in hard_gate_scores
    )
    semantic_scores = [
        score
        for score in scores
        if is_semantic_score(score)
        and score.status is not EvalScoreStatus.NOT_APPLICABLE
    ]
    semantic_evaluated = bool(semantic_scores)
    semantic_success = semantic_evaluated and all(
        score.status is EvalScoreStatus.PASSED for score in semantic_scores
    )
    trace_complete = record.observability.trace_completeness.complete
    runtime_success = record.final_status == "succeeded" and trace_complete

    reasons: list[str] = []
    if record.final_status != "succeeded":
        reasons.append("runtime_failure")
    if not trace_complete:
        reasons.append("trace_incomplete")
    if not hard_gate_passed:
        reasons.append("hard_gate_failure")
    if not semantic_evaluated:
        reasons.append("semantic_not_evaluated")
    elif not semantic_success:
        reasons.append("semantic_failure")

    selection_passed = any(
        score.metric_name in _TOOL_SELECTION_METRICS
        and score.status is EvalScoreStatus.PASSED
        for score in semantic_scores
    )
    if selection_passed and any(
        call.status is EvalToolStatus.FAILED for call in record.tool_calls
    ):
        reasons.append("tool_selection_execution_conflict")

    if record.final_status == "succeeded" and any(
        item.status.value == "failed" for item in record.external_ios
    ):
        reasons.append("dependency_failure_with_success")

    if any(
        call.effect is EvalToolEffect.EXTERNAL
        and call.status is EvalToolStatus.COMPLETED
        and call.approval_status is not EvalApprovalStatus.APPROVED
        for call in record.tool_calls
    ):
        reasons.append("external_approval_evidence_missing")

    reasons.extend(str(reason) for reason in extra_review_reasons if str(reason))
    normalized_reasons = tuple(dict.fromkeys(reasons))
    complete_success = runtime_success and semantic_success and hard_gate_passed
    return EvalCaseOutcome(
        runtime_success=runtime_success,
        semantic_evaluated=semantic_evaluated,
        semantic_success=semantic_success,
        hard_gate_passed=hard_gate_passed,
        complete_success=complete_success,
        review_required=bool(normalized_reasons),
        review_reasons=normalized_reasons,
    )
