"""DeepEval semantic evaluator contracts without network or real judge credentials."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from evaluation.adapters.deepeval_adapter import DeepEvalAdapter
from evaluation.evaluators.judges.deepeval import (
    DeepEvalJudgeEvaluator,
    DeepEvalMetricBinding,
    GovernedDeepEvalModel,
)
from evaluation.registry import EvaluatorKind, EvaluatorRegistry
from evaluation.runners import (
    AgentAdapterRegistry,
    AgentEvalRunner,
    CallableAgentAdapter,
    EvaluationCaseSpec,
)
from evaluation.schemas import (
    EvalScore,
    EvalScoreStatus,
    EvalToolCall,
    EvalToolStatus,
    ScoreSource,
)


class _SuccessfulMetric:
    """Small DeepEval-like metric used to verify local score normalization."""

    threshold = 0.7
    score = None
    reason = None

    async def a_measure(self, _test_case: Any, **_kwargs: Any) -> float:
        self.score = 0.9
        self.reason = "The actual output satisfies the bounded rubric."
        return self.score

    def is_successful(self) -> bool:
        return True


class _FailingMetric:
    """DeepEval-like metric that fails with a secret-bearing provider error."""

    threshold = 0.7
    score = None
    reason = None

    async def a_measure(self, _test_case: Any, **_kwargs: Any) -> float:
        raise RuntimeError("api_key=sk-12345678901234567890")


class _RecordingEvaluator:
    """Case-aware evaluator stub used to prove runner ordering and opt-in behavior."""

    def __init__(self, name: str, kind: EvaluatorKind, calls: list[str]) -> None:
        self.name = name
        self.kind = kind
        self.calls = calls

    async def evaluate(self, _record: Any, *, case: EvaluationCaseSpec | None = None):
        assert case is not None
        self.calls.append(self.name)
        return (
            EvalScore(
                metric_name=self.name,
                dimension="test",
                evaluator_name=self.name,
                source=(
                    ScoreSource.DETERMINISTIC
                    if self.kind is EvaluatorKind.DETERMINISTIC
                    else ScoreSource.JUDGE
                ),
                status=EvalScoreStatus.PASSED,
                value=1.0,
            ),
        )


def _case() -> EvaluationCaseSpec:
    return EvaluationCaseSpec(
        case_id="case-deepeval",
        case_version="v1",
        dataset_version="dataset-v1",
        input_payload={
            "question": "Explain idempotency",
            "api_config": {
                "smart": {
                    "api_key": "sk-12345678901234567890",
                    "base_url": "https://example.invalid/v1",
                    "model": "judge-model",
                }
            },
        },
        expected_output={"answer": "Use a stable business key"},
        expected_tool_calls=("search_question_bank",),
        quality_rubric={
            "focus": "answer_is_grounded_and_actionable",
            "expected_tool_arguments": {
                "search_question_bank": {"query": "idempotency"}
            },
        },
    )


def _record(case: EvaluationCaseSpec):
    record = AgentEvalRunner.minimal_record_for_test(
        case=case,
        actual_output={"answer": "Use a stable business key and persist state."},
    )
    return record.model_copy(
        update={
            "tool_calls": (
                EvalToolCall(
                    call_id="tool-1",
                    sequence=1,
                    tool_name="search_question_bank",
                    status=EvalToolStatus.COMPLETED,
                    arguments_summary={"query": "idempotency"},
                    result_summary={"count": 2},
                    simulated=True,
                ),
            )
        }
    )


@pytest.mark.fast
def test_adapter_maps_tools_and_excludes_request_credentials_from_test_case() -> None:
    """DeepEval test cases may contain governed content but never request credentials."""

    case = _case()
    test_case = DeepEvalAdapter().to_llm_test_case(case=case, record=_record(case))

    assert "sk-" not in test_case.input
    assert "api_config" not in test_case.input
    assert test_case.metadata["case_id"] == case.case_id
    assert test_case.tools_called[0].name == "search_question_bank"
    assert test_case.tools_called[0].input_parameters == {"query": "idempotency"}
    assert test_case.expected_tools[0].input_parameters == {"query": "idempotency"}


@pytest.mark.asyncio
@pytest.mark.fast
async def test_default_tool_metric_reuses_deepeval_deterministic_contract() -> None:
    """The production metric builder executes DeepEval tool correctness offline."""

    case = _case().model_copy(
        update={
            "input_payload": {"question": "Explain idempotency"},
            "quality_rubric": {
                "expected_tool_arguments": {
                    "search_question_bank": {"query": "idempotency"}
                }
            },
        }
    )

    scores = await DeepEvalJudgeEvaluator().evaluate(_record(case), case=case)

    assert [score.metric_name for score in scores] == ["deepeval.tool_correctness"]
    assert scores[0].status is EvalScoreStatus.PASSED
    assert scores[0].value == 1.0


@pytest.mark.asyncio
@pytest.mark.fast
async def test_judge_maps_metric_score_reason_threshold_and_version() -> None:
    """Successful DeepEval metrics retain provenance in the local score model."""

    case = _case()
    evaluator = DeepEvalJudgeEvaluator(
        metric_builder=lambda **_kwargs: (
            DeepEvalMetricBinding(
                metric_name="deepeval.business_rubric",
                dimension="final_output_quality",
                metric=_SuccessfulMetric(),
            ),
        )
    )

    scores = await evaluator.evaluate(_record(case), case=case)

    assert len(scores) == 1
    score = scores[0]
    assert score.source is ScoreSource.JUDGE
    assert score.status is EvalScoreStatus.PASSED
    assert score.value == 0.9
    assert score.threshold == 0.7
    assert score.reason == "The actual output satisfies the bounded rubric."
    assert score.metric_version.startswith("deepeval-4.1.10:")


@pytest.mark.asyncio
@pytest.mark.fast
async def test_judge_failure_becomes_sanitized_review_score() -> None:
    """Judge dependency errors require review without exposing secrets or changing output."""

    case = _case()
    record = _record(case)
    evaluator = DeepEvalJudgeEvaluator(
        metric_builder=lambda **_kwargs: (
            DeepEvalMetricBinding(
                metric_name="deepeval.business_rubric",
                dimension="final_output_quality",
                metric=_FailingMetric(),
            ),
        )
    )

    scores = await evaluator.evaluate(record, case=case)

    assert record.final_output == {"answer": "Use a stable business key and persist state."}
    assert scores[0].status is EvalScoreStatus.REVIEW_REQUIRED
    assert scores[0].value is None
    assert scores[0].reason_code == "judge_runtime_error"
    assert "sk-" not in (scores[0].reason or "")
    assert "REDACTED" in (scores[0].reason or "")


@pytest.mark.asyncio
@pytest.mark.fast
async def test_runner_executes_judge_only_when_enabled_and_after_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The persisted run switch controls judge execution without changing actual output."""

    monkeypatch.setattr("observability.get_langfuse_client", lambda: None)

    async def production_entry(payload: dict[str, Any], *_args: Any):
        return {"answer": payload["question"]}

    adapters = AgentAdapterRegistry()
    adapters.register(
        CallableAgentAdapter(
            name="test-agent",
            version="v1",
            entrypoint=production_entry,
        )
    )
    calls: list[str] = []
    evaluators = EvaluatorRegistry()
    evaluators.register(_RecordingEvaluator("judge", EvaluatorKind.JUDGE, calls))
    evaluators.register(_RecordingEvaluator("rule", EvaluatorKind.DETERMINISTIC, calls))
    runner = AgentEvalRunner(adapter_registry=adapters, evaluator_registry=evaluators)
    case = _case().model_copy(update={"input_payload": {"question": "actual"}})

    disabled = await runner.run_case(
        case=case,
        agent_name="test-agent",
        model_config_hash="sha256:model",
        owner_scope_hash="sha256:owner",
        run_id="judge-disabled",
        include_judges=False,
    )
    enabled = await runner.run_case(
        case=case,
        agent_name="test-agent",
        model_config_hash="sha256:model",
        owner_scope_hash="sha256:owner",
        run_id="judge-enabled",
        include_judges=True,
    )

    assert calls == ["rule", "rule", "judge"]
    assert disabled.record.final_output == {"answer": "actual"}
    assert enabled.record.final_output == {"answer": "actual"}


@pytest.mark.asyncio
@pytest.mark.fast
async def test_governed_model_uses_request_gateway_without_confident_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepEval prompts must use the existing model gateway and local-only reporting policy."""

    calls: list[dict[str, Any]] = []

    async def fake_invoke_text(prompt: str, api_config: dict[str, Any], **kwargs: Any):
        calls.append({"prompt": prompt, "api_config": api_config, **kwargs})
        return SimpleNamespace(content='{"score": 1, "reason": "ok"}')

    monkeypatch.delenv("CONFIDENT_API_KEY", raising=False)
    monkeypatch.setattr("ai.llm.llms.invoke_text", fake_invoke_text)
    api_config = _case().input_payload["api_config"]
    model = GovernedDeepEvalModel(api_config=api_config)

    response = await model.a_generate("Return judge JSON")

    assert response == '{"score": 1, "reason": "ok"}'
    assert calls[0]["api_config"] == api_config
    assert calls[0]["channel"] == "smart"
    assert calls[0]["call_metadata"]["source"] == "deepeval_judge"
    assert __import__("os").environ["DEEPEVAL_TELEMETRY_OPT_OUT"] == "true"
    assert __import__("os").environ["DEEPEVAL_TELEMETRY_ENABLED"] == "false"
