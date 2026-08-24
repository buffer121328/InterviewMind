"""Governed DeepEval metrics mapped into the local evaluation score contract."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

from app.security.security import safe_error_message
from evaluation.adapters.deepeval_adapter import DeepEvalAdapter
from evaluation.extractors.runtime import sanitize_evaluation_value
from evaluation.registry import EvaluatorKind
from evaluation.runners.base import EvaluationCaseSpec
from evaluation.schemas import (
    AgentEvalRecord,
    EvalScore,
    EvalScoreStatus,
    ScoreSource,
)

# The open-source evaluator runs locally. Vendor telemetry and error reporting
# remain disabled even when this module is imported by the production registry.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "true")
os.environ.setdefault("DEEPEVAL_TELEMETRY_ENABLED", "false")
os.environ.setdefault("ERROR_REPORTING", "false")
os.environ.setdefault("DEEPEVAL_FILE_SYSTEM", "READ_ONLY")


@dataclass(frozen=True, slots=True)
class DeepEvalMetricBinding:
    """Attach stable product metadata to one DeepEval metric instance."""

    metric_name: str
    dimension: str
    metric: Any


MetricBuilder = Callable[..., Sequence[DeepEvalMetricBinding]]


class GovernedDeepEvalModel:
    """Create a DeepEval model that delegates every prompt to the model gateway."""

    def __new__(cls, *, api_config: dict[str, Any]):
        from deepeval.models import DeepEvalBaseLLM

        class _GatewayModel(DeepEvalBaseLLM):
            def __init__(self, config: dict[str, Any]) -> None:
                self._api_config = dict(config)
                super().__init__(model="governed-model-gateway")

            def load_model(self):
                return self

            def generate(self, *_args: Any, **_kwargs: Any) -> str:
                raise RuntimeError("governed DeepEval judge supports async evaluation only")

            async def a_generate(self, prompt: Any, *_args: Any, **_kwargs: Any) -> str:
                from ai.llm.llms import invoke_text

                response = await invoke_text(
                    _prompt_text(prompt),
                    self._api_config,
                    channel="smart",
                    max_tokens=2400,
                    call_metadata={
                        "source": "deepeval_judge",
                        "operation": "semantic_evaluation",
                    },
                )
                return _response_text(response)

            def get_model_name(self, *_args: Any, **_kwargs: Any) -> str:
                return "governed-model-gateway"

        return _GatewayModel(api_config)


class DeepEvalJudgeEvaluator:
    """Execute bounded DeepEval metrics and fail Judge errors to human review."""

    name = "deepeval_semantic_judge"
    kind = EvaluatorKind.JUDGE

    def __init__(
        self,
        *,
        adapter: DeepEvalAdapter | None = None,
        metric_builder: MetricBuilder | None = None,
    ) -> None:
        self._adapter = adapter or DeepEvalAdapter()
        self._metric_builder = metric_builder or _default_metric_builder

    async def evaluate(
        self,
        record: AgentEvalRecord,
        *,
        case: EvaluationCaseSpec | None = None,
    ) -> tuple[EvalScore, ...]:
        """Evaluate one real output without mutating the record or Golden case."""

        if case is None:
            return (self._not_applicable("case_not_available"),)
        if record.final_status != "succeeded":
            return (self._not_applicable("agent_runtime_failed"),)

        test_case = self._adapter.to_llm_test_case(case=case, record=record)
        api_config = case.input_payload.get("api_config")
        model = (
            GovernedDeepEvalModel(api_config=dict(api_config))
            if isinstance(api_config, dict) and api_config
            else None
        )
        try:
            bindings = tuple(
                self._metric_builder(
                    case=case,
                    record=record,
                    test_case=test_case,
                    model=model,
                )
            )
        except Exception as exc:  # metric construction is a reviewable dependency error
            return (self._review_score("deepeval.metric_setup", exc),)
        if not bindings:
            return (self._not_applicable("no_supported_metric"),)

        scores: list[EvalScore] = []
        for binding in bindings:
            try:
                await binding.metric.a_measure(test_case, _show_indicator=False)
                scores.append(_score_from_metric(binding, case_id=case.case_id))
            except Exception as exc:  # noqa: BLE001 - Judge failures remain case evidence
                scores.append(self._review_score(binding.metric_name, exc, binding.metric))
        return tuple(scores)

    def _not_applicable(self, reason_code: str) -> EvalScore:
        return EvalScore(
            metric_name="deepeval.semantic",
            dimension="final_output_quality",
            evaluator_name=self.name,
            source=ScoreSource.JUDGE,
            status=EvalScoreStatus.NOT_APPLICABLE,
            reason_code=reason_code,
            metric_version=_metric_version(None),
        )

    def _review_score(
        self,
        metric_name: str,
        error: Exception,
        metric: Any | None = None,
    ) -> EvalScore:
        return EvalScore(
            metric_name=metric_name,
            dimension="final_output_quality",
            evaluator_name=self.name,
            source=ScoreSource.JUDGE,
            status=EvalScoreStatus.REVIEW_REQUIRED,
            value=None,
            threshold=_finite_number(getattr(metric, "threshold", None)),
            reason_code="judge_runtime_error",
            reason=_safe_reason(safe_error_message(error)),
            metric_version=_metric_version(metric),
        )


def _default_metric_builder(
    *,
    case: EvaluationCaseSpec,
    record: AgentEvalRecord,
    test_case: Any,
    model: Any | None,
) -> tuple[DeepEvalMetricBinding, ...]:
    """Choose a small calibrated metric set from fields the case actually owns."""

    del record, test_case
    from deepeval.metrics import GEval, ToolCorrectnessMetric
    from deepeval.test_case.llm_test_case import SingleTurnParams, ToolCallParams

    bindings: list[DeepEvalMetricBinding] = []
    if case.expected_tool_calls:
        expected_arguments = case.quality_rubric.get("expected_tool_arguments")
        evaluation_params = (
            [ToolCallParams.INPUT_PARAMETERS]
            if isinstance(expected_arguments, dict) and expected_arguments
            else []
        )
        bindings.append(
            DeepEvalMetricBinding(
                metric_name="deepeval.tool_correctness",
                dimension="tool_use",
                metric=ToolCorrectnessMetric(
                    threshold=1.0,
                    evaluation_params=evaluation_params,
                    model=_offline_metric_model(),
                    include_reason=False,
                    async_mode=True,
                ),
            )
        )

    focus = case.quality_rubric.get("focus")
    if isinstance(focus, str) and focus.strip() and model is not None:
        params = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT]
        if case.expected_output is not None:
            params.append(SingleTurnParams.EXPECTED_OUTPUT)
        if case.expected_facts:
            params.append(SingleTurnParams.CONTEXT)
        criteria = (
            "Evaluate whether the actual output satisfies this bounded business goal: "
            f"{focus.strip()}. Use expected output and context only as references. "
            "Do not reward claims that are unsupported by the supplied references."
        )
        bindings.append(
            DeepEvalMetricBinding(
                metric_name="deepeval.business_rubric",
                dimension="final_output_quality",
                metric=GEval(
                    name="Business rubric compliance",
                    criteria=criteria,
                    evaluation_params=params,
                    model=model,
                    threshold=0.7,
                    async_mode=True,
                ),
            )
        )
    return tuple(bindings)


def _score_from_metric(
    binding: DeepEvalMetricBinding,
    *,
    case_id: str,
) -> EvalScore:
    metric = binding.metric
    value = _finite_number(getattr(metric, "score", None))
    threshold = _finite_number(getattr(metric, "threshold", None))
    successful = metric.is_successful()
    status = (
        EvalScoreStatus.REVIEW_REQUIRED
        if value is None or successful is None
        else EvalScoreStatus.PASSED
        if bool(successful)
        else EvalScoreStatus.FAILED
    )
    return EvalScore(
        metric_name=binding.metric_name,
        dimension=binding.dimension,
        evaluator_name="deepeval_semantic_judge",
        source=ScoreSource.JUDGE,
        status=status,
        value=value,
        threshold=threshold,
        reason_code=None if status is not EvalScoreStatus.REVIEW_REQUIRED else "invalid_metric_result",
        reason=_safe_reason(getattr(metric, "reason", None)),
        metric_version=_metric_version(metric),
        evidence_refs=(f"case:{case_id}:actual-output",),
    )


def _safe_reason(value: Any) -> str | None:
    if value is None:
        return None
    sanitized, _findings = sanitize_evaluation_value(
        str(value),
        location="judge_score.reason",
    )
    if not isinstance(sanitized, str):
        sanitized = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
    return sanitized[:2000]


def _metric_version(metric: Any | None) -> str:
    metric_name = type(metric).__name__ if metric is not None else "semantic"
    return f"deepeval-{version('deepeval')}:{metric_name}"[:80]


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if result == result and abs(result) != float("inf") else None


def _prompt_text(prompt: Any) -> str:
    if isinstance(prompt, str):
        return prompt
    return json.dumps(prompt, ensure_ascii=False, sort_keys=True, default=str)


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)


def _offline_metric_model() -> Any:
    """Satisfy DeepEval construction while proving deterministic metrics stay offline."""

    from deepeval.models import DeepEvalBaseLLM

    class _OfflineModel(DeepEvalBaseLLM):
        def load_model(self):
            return self

        def generate(self, *_args: Any, **_kwargs: Any) -> str:
            raise AssertionError("deterministic DeepEval metric attempted a model call")

        async def a_generate(self, *_args: Any, **_kwargs: Any) -> str:
            raise AssertionError("deterministic DeepEval metric attempted a model call")

        def get_model_name(self, *_args: Any, **_kwargs: Any) -> str:
            return "offline-deterministic-metric"

    return _OfflineModel(model="offline-deterministic-metric")
