"""不调用模型的 Dataset Case 契约评测器。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from evaluation.runners.base import EvaluationCaseSpec
from evaluation.schemas import (
    AgentEvalRecord,
    EvalScore,
    EvalScoreStatus,
    ScoreSource,
)


class DeterministicCaseContractEvaluator:
    """评估 Golden 中可由结构化事实确定的输出、工具、流程和预算契约。"""

    name = "deterministic_case_contracts"

    def evaluate(
        self,
        *,
        case: EvaluationCaseSpec,
        record: AgentEvalRecord,
    ) -> tuple[EvalScore, ...]:
        """返回只引用 case/call/event 标识的确定性 Score，不复制 Golden 正文。"""

        scores: list[EvalScore] = []
        output_text = _normalized(record.final_output)
        if case.expected_output is not None:
            scores.append(
                _binary_score(
                    metric_name="case.expected_output_match",
                    dimension="final_output_quality",
                    passed=record.final_output == case.expected_output,
                    evidence_refs=(f"case:{case.case_id}:expected-output",),
                )
            )
        if case.expected_facts:
            matched = [
                _normalized(item) in output_text for item in case.expected_facts
            ]
            scores.append(
                _ratio_score(
                    metric_name="factual.expected_fact_coverage",
                    dimension="factuality_and_evidence",
                    matches=matched,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:expected-fact:{index}"
                        for index, passed in enumerate(matched)
                        if not passed
                    ),
                )
            )
        if case.forbidden_claims:
            absent = [
                _normalized(item) not in output_text for item in case.forbidden_claims
            ]
            scores.append(
                _ratio_score(
                    metric_name="factual.forbidden_claim_absence",
                    dimension="factuality_and_evidence",
                    matches=absent,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:forbidden-claim:{index}"
                        for index, passed in enumerate(absent)
                        if not passed
                    ),
                )
            )

        actual_tools = [call.tool_name for call in record.tool_calls]
        if case.expected_tool_calls:
            expected = tuple(dict.fromkeys(case.expected_tool_calls))
            matched = [name in actual_tools for name in expected]
            scores.append(
                _ratio_score(
                    metric_name="tool.expected_call_coverage",
                    dimension="tool_use",
                    matches=matched,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:expected-tool:{index}"
                        for index, passed in enumerate(matched)
                        if not passed
                    ),
                )
            )
        if case.allowed_tool_calls:
            allowed = set(case.allowed_tool_calls)
            invalid_calls = [
                call for call in record.tool_calls if call.tool_name not in allowed
            ]
            scores.append(
                _binary_score(
                    metric_name="tool.allowed_call_compliance",
                    dimension="tool_use",
                    passed=not invalid_calls,
                    evidence_refs=tuple(
                        f"tool-call:{call.call_id}" for call in invalid_calls
                    ),
                )
            )

        transitions = {
            *(step.stage for step in record.steps),
            *(event.event_type for event in record.events),
        }
        if case.required_state_transitions:
            matched = [name in transitions for name in case.required_state_transitions]
            scores.append(
                _ratio_score(
                    metric_name="workflow.required_state_transition_coverage",
                    dimension="planning_and_execution",
                    matches=matched,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:required-transition:{index}"
                        for index, passed in enumerate(matched)
                        if not passed
                    ),
                )
            )
        if case.forbidden_state_transitions:
            absent = [name not in transitions for name in case.forbidden_state_transitions]
            scores.append(
                _ratio_score(
                    metric_name="workflow.forbidden_state_transition_compliance",
                    dimension="planning_and_execution",
                    matches=absent,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:forbidden-transition:{index}"
                        for index, passed in enumerate(absent)
                        if not passed
                    ),
                )
            )

        question_count = case.quality_rubric.get("question_count")
        if isinstance(question_count, int) and question_count >= 0:
            scores.append(
                _binary_score(
                    metric_name="rubric.question_count_compliance",
                    dimension="final_output_quality",
                    passed=_output_item_count(record.final_output) == question_count,
                    evidence_refs=(f"case:{case.case_id}:rubric:question-count",),
                )
            )

        total_tokens = record.token_usage.total_tokens or (
            record.token_usage.input_tokens + record.token_usage.output_tokens
        )
        if case.latency_budget_ms is not None:
            scores.append(
                _binary_score(
                    metric_name="budget.latency_compliance",
                    dimension="model_routing_cost_latency",
                    passed=record.latency_ms <= case.latency_budget_ms,
                    evidence_refs=(f"case:{case.case_id}:latency-budget",),
                )
            )
        if case.token_budget is not None:
            scores.append(
                _binary_score(
                    metric_name="budget.token_compliance",
                    dimension="model_routing_cost_latency",
                    passed=total_tokens <= case.token_budget,
                    evidence_refs=(f"case:{case.case_id}:token-budget",),
                )
            )
        return tuple(scores)


def _normalized(value: Any) -> str:
    """把结构化值规范化为只用于本地确定性包含判断的文本。"""

    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return re.sub(r"\s+", "", serialized).lower().strip('"')


def _output_item_count(value: Any) -> int | None:
    """从常见结构化输出中提取题目数量；无法确定时返回 None。"""

    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("questions", "interview_plan", "items"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return len(candidate)
    return None


def _binary_score(
    *,
    metric_name: str,
    dimension: str,
    passed: bool,
    evidence_refs: Iterable[str] = (),
) -> EvalScore:
    """构造阈值为 1 的二元确定性 Score。"""

    return EvalScore(
        metric_name=metric_name,
        dimension=dimension,
        evaluator_name="deterministic_case_contracts",
        source=ScoreSource.DETERMINISTIC,
        status=EvalScoreStatus.PASSED if passed else EvalScoreStatus.FAILED,
        value=1.0 if passed else 0.0,
        threshold=1.0,
        reason_code=None if passed else metric_name,
        evidence_refs=tuple(evidence_refs),
    )


def _ratio_score(
    *,
    metric_name: str,
    dimension: str,
    matches: list[bool],
    evidence_refs: Iterable[str] = (),
) -> EvalScore:
    """构造要求全部命中的比例 Score。"""

    value = sum(matches) / len(matches) if matches else 1.0
    return EvalScore(
        metric_name=metric_name,
        dimension=dimension,
        evaluator_name="deterministic_case_contracts",
        source=ScoreSource.DETERMINISTIC,
        status=EvalScoreStatus.PASSED if value == 1.0 else EvalScoreStatus.FAILED,
        value=value,
        threshold=1.0,
        reason_code=None if value == 1.0 else metric_name,
        evidence_refs=tuple(evidence_refs),
    )
