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
    EvalToolStatus,
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
        output_text = _primary_output_text(case, record.final_output)
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

        completed_tools = [
            call.tool_name
            for call in record.tool_calls
            if call.status is EvalToolStatus.COMPLETED
        ]
        tool_applicability = case.quality_rubric.get("tool_applicability")
        if tool_applicability == "not_applicable":
            scores.append(
                EvalScore(
                    metric_name="tool.contract_applicability",
                    dimension="tool_use",
                    evaluator_name=self.name,
                    source=ScoreSource.DETERMINISTIC,
                    status=EvalScoreStatus.NOT_APPLICABLE,
                    value=None,
                    reason_code="tool_not_required",
                )
            )
        elif tool_applicability == "forbidden":
            scores.append(
                _binary_score(
                    metric_name="tool.forbidden_call_compliance",
                    dimension="tool_use",
                    passed=not record.tool_calls,
                    evidence_refs=tuple(
                        f"tool-call:{call.call_id}" for call in record.tool_calls
                    ),
                )
            )
        if case.expected_tool_calls:
            expected = tuple(dict.fromkeys(case.expected_tool_calls))
            matched = [name in completed_tools for name in expected]
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
        expected_arguments = case.quality_rubric.get("expected_tool_arguments")
        if isinstance(expected_arguments, dict) and all(
            isinstance(name, str) and isinstance(arguments, dict)
            for name, arguments in expected_arguments.items()
        ):
            matched = [name in completed_tools for name in expected_arguments]
            scores.append(
                _ratio_score(
                    metric_name="tool.key_argument_contract_compliance",
                    dimension="tool_use",
                    matches=matched,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:tool-arguments:{index}"
                        for index, passed in enumerate(matched)
                        if not passed
                    ),
                )
            )
        tool_result_facts = case.quality_rubric.get("tool_result_facts")
        if isinstance(tool_result_facts, list) and all(
            isinstance(fact, str) and fact.strip() for fact in tool_result_facts
        ):
            fixture_tools_completed = bool(case.expected_tool_calls) and all(
                name in completed_tools for name in case.expected_tool_calls
            )
            matched = [
                fixture_tools_completed and _normalized(fact) in output_text
                for fact in tool_result_facts
            ]
            scores.append(
                _ratio_score(
                    metric_name="tool.fixture_result_adoption",
                    dimension="tool_use",
                    matches=matched,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:tool-result-fact:{index}"
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

        if case.required_workflow_tool_calls:
            required = tuple(dict.fromkeys(case.required_workflow_tool_calls))
            scores.append(
                _ratio_score(
                    metric_name="workflow.required_tool_call_coverage",
                    dimension="planning_and_execution",
                    matches=[name in completed_tools for name in required],
                    evidence_refs=tuple(
                        f"case:{case.case_id}:required-workflow-tool:{index}"
                        for index, name in enumerate(required)
                        if name not in completed_tools
                    ),
                )
            )
        if case.degraded_workflow_tool_calls:
            expected = tuple(dict.fromkeys(case.degraded_workflow_tool_calls))
            failed = {call.tool_name for call in record.tool_calls if call.status is EvalToolStatus.FAILED}
            scores.append(
                _ratio_score(
                    metric_name="workflow.tool_degradation_compliance",
                    dimension="planning_and_execution",
                    matches=[
                        name in failed and record.final_status == "succeeded"
                        for name in expected
                    ],
                    evidence_refs=tuple(
                        f"case:{case.case_id}:degraded-workflow-tool:{index}"
                        for index, name in enumerate(expected)
                        if name not in failed or record.final_status != "succeeded"
                    ),
                )
            )
        if case.blocked_workflow_tool_calls:
            expected = tuple(dict.fromkeys(case.blocked_workflow_tool_calls))
            blocked = {call.tool_name for call in record.tool_calls if call.status is EvalToolStatus.BLOCKED}
            scores.append(
                _ratio_score(
                    metric_name="workflow.external_effect_interception",
                    dimension="security_and_permissions",
                    matches=[name in blocked for name in expected],
                    evidence_refs=tuple(
                        f"case:{case.case_id}:blocked-workflow-tool:{index}"
                        for index, name in enumerate(expected)
                        if name not in blocked
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

        required_output_paths = case.quality_rubric.get("required_output_paths")
        if isinstance(required_output_paths, list) and all(
            isinstance(path, str) and path.strip() for path in required_output_paths
        ):
            matched = [
                _output_path_value(record.final_output, path) is not None
                for path in required_output_paths
            ]
            scores.append(
                _ratio_score(
                    metric_name="rubric.required_output_path_coverage",
                    dimension="final_output_quality",
                    matches=matched,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:required-output-path:{index}"
                        for index, passed in enumerate(matched)
                        if not passed
                    ),
                )
            )

        expected_output_values = case.quality_rubric.get("expected_output_values")
        if isinstance(expected_output_values, dict) and all(
            isinstance(path, str) and path.strip()
            for path in expected_output_values
        ):
            matched = [
                _output_path_value(record.final_output, path) == expected
                for path, expected in expected_output_values.items()
            ]
            scores.append(
                _ratio_score(
                    metric_name="rubric.expected_output_value_coverage",
                    dimension="planning_and_execution",
                    matches=matched,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:expected-output-value:{index}"
                        for index, passed in enumerate(matched)
                        if not passed
                    ),
                )
            )

        forbidden_output_text = case.quality_rubric.get("forbidden_output_text")
        if isinstance(forbidden_output_text, list) and all(
            isinstance(value, str) and value for value in forbidden_output_text
        ):
            absent = [_normalized(value) not in output_text for value in forbidden_output_text]
            scores.append(
                _ratio_score(
                    metric_name="rubric.forbidden_output_text_absence",
                    dimension="final_output_quality",
                    matches=absent,
                    evidence_refs=tuple(
                        f"case:{case.case_id}:forbidden-output-text:{index}"
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


def _primary_output_text(case: EvaluationCaseSpec, output: Any) -> str:
    """Serialize the case's user-facing output projection for text checks."""

    rubric = case.quality_rubric
    if "primary_output_paths" not in rubric:
        return _normalized(output)
    paths = rubric.get("primary_output_paths")
    if not isinstance(paths, list) or not paths or not all(
        isinstance(path, str) and path.strip() for path in paths
    ):
        return ""
    values = [
        selected
        for path in paths
        for selected in _output_path_values(output, path)
        if selected not in (None, "")
    ]
    return _normalized(values)


def _output_path_values(value: Any, path: str) -> tuple[Any, ...]:
    """Resolve object keys and ``[]`` list wildcards from a structured output."""

    current: tuple[Any, ...] = (value,)
    for part in path.split("."):
        if not part:
            return ()
        next_values: list[Any] = []
        if part == "[]":
            for item in current:
                if isinstance(item, list):
                    next_values.extend(item)
        else:
            for item in current:
                if isinstance(item, dict) and part in item:
                    next_values.append(item[part])
        current = tuple(next_values)
        if not current:
            return ()
    return current


def _output_path_value(value: Any, path: str) -> Any | None:
    """读取点分输出路径；缺失与显式空值都不满足案例契约。"""

    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current if current not in (None, "") else None


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
