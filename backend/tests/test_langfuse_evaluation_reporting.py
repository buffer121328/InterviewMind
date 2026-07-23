"""Offline tests for Langfuse evaluation score reporting helpers."""

from dataclasses import dataclass


@dataclass
class FakeMetric:
    name: str
    score: float | None = None
    success: bool | None = None
    reason: str | None = None
    threshold: float | None = None
    evaluation_model: str | None = None


def test_build_score_from_deepeval_like_metric():
    from app.langfuse.evaluation_reporting import build_score_from_metric

    score = build_score_from_metric(
        FakeMetric(
            name="faithfulness",
            score=0.87,
            reason="事实一致",
            threshold=0.7,
            evaluation_model="gpt-judge",
        ),
        trace_id="trace-1",
        dataset_run_id="dataset-run-1",
        metadata={"suite": "resume"},
    )

    assert score.name == "eval.faithfulness"
    assert score.value == 0.87
    assert score.data_type == "NUMERIC"
    assert score.comment == "事实一致"
    assert score.trace_id == "trace-1"
    assert score.dataset_run_id == "dataset-run-1"
    assert score.metadata["threshold"] == 0.7
    assert score.metadata["evaluation_model"] == "gpt-judge"
    assert score.metadata["suite"] == "resume"


def test_build_score_from_boolean_metric_dict():
    from app.langfuse.evaluation_reporting import build_score_from_metric

    score = build_score_from_metric({"name": "schema_valid", "success": True}, score_prefix="")

    assert score.name == "schema_valid"
    assert score.value is True
    assert score.data_type == "BOOLEAN"


def test_report_score_is_opt_in(monkeypatch):
    from app.langfuse.evaluation_reporting import EvaluationScore, report_score

    calls = []
    monkeypatch.setattr("app.langfuse.evaluation_reporting.record_score", lambda **kwargs: calls.append(kwargs) or True)
    monkeypatch.delenv("LANGFUSE_EVAL_REPORTING_ENABLED", raising=False)

    assert report_score(EvaluationScore(name="eval.test", value=1.0)) is False
    assert calls == []

    monkeypatch.setenv("LANGFUSE_EVAL_REPORTING_ENABLED", "true")
    assert report_score(EvaluationScore(name="eval.test", value=1.0, trace_id="trace-1")) is True
    assert calls[0]["name"] == "eval.test"
    assert calls[0]["trace_id"] == "trace-1"


def test_report_metrics_summarizes_success(monkeypatch):
    from app.langfuse.evaluation_reporting import report_metrics

    recorded = []
    monkeypatch.setattr("app.langfuse.evaluation_reporting.record_score", lambda **kwargs: recorded.append(kwargs) or True)

    summary = report_metrics(
        [FakeMetric(name="quality", score=0.9), {"name": "schema", "success": True}],
        trace_id="trace-1",
        metadata={"suite": "dialogue"},
        force=True,
    )

    assert summary == {"attempted": 2, "reported": 2, "failed": 0}
    assert [item["name"] for item in recorded] == ["eval.quality", "eval.schema"]
    assert recorded[0]["metadata"]["suite"] == "dialogue"


def test_report_deepeval_assertion_uses_safe_metadata_and_env_targets(monkeypatch):
    from app.langfuse.evaluation_reporting import report_deepeval_assertion

    recorded = []
    monkeypatch.setattr("app.langfuse.evaluation_reporting.record_score", lambda **kwargs: recorded.append(kwargs) or True)
    monkeypatch.setenv("LANGFUSE_EVAL_TRACE_ID", "trace-env")
    monkeypatch.setenv("LANGFUSE_EVAL_DATASET_RUN_ID", "dataset-run-env")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/eval.py::test_case (call)")

    class TestCase:
        name = "case-name"
        input = "private resume text should not be reported"
        actual_output = "private output should not be reported"

    summary = report_deepeval_assertion(
        metrics=[FakeMetric(name="quality", score=0.8)],
        test_case=TestCase(),
        force=True,
    )

    assert summary == {"attempted": 1, "reported": 1, "failed": 0}
    assert recorded[0]["trace_id"] == "trace-env"
    assert recorded[0]["dataset_run_id"] == "dataset-run-env"
    assert recorded[0]["metadata"]["pytest_current_test"] == "tests/eval.py::test_case (call)"
    assert recorded[0]["metadata"]["test_case_name"] == "case-name"
    assert "private resume" not in str(recorded[0])
