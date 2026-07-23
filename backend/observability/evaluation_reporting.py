"""Utilities for reporting offline evaluation results to Langfuse.

The production app already records traces for Agent runs. This module is the
bridge for offline/CI evaluation suites (for example DeepEval): convert metric
objects or simple dicts into Langfuse scores without requiring tests to know the
Langfuse SDK shape.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from observability import record_score

ScoreDataType = Literal["NUMERIC", "CATEGORICAL", "BOOLEAN", "TEXT", "CORRECTION"]


@dataclass(frozen=True, slots=True)
class EvaluationScore:
    """A Langfuse score payload produced by an offline evaluator."""

    name: str
    value: float | str | bool
    data_type: ScoreDataType | None = None
    comment: str | None = None
    trace_id: str | None = None
    observation_id: str | None = None
    session_id: str | None = None
    dataset_run_id: str | None = None
    score_id: str | None = None
    config_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluation_reporting_enabled() -> bool:
    """Return whether offline evaluation results should be sent to Langfuse."""

    return os.getenv("LANGFUSE_EVAL_REPORTING_ENABLED", "false").lower() in {"1", "true", "yes"}


def _metric_attr(metric: Any, name: str, default: Any = None) -> Any:
    if isinstance(metric, dict):
        return metric.get(name, default)
    return getattr(metric, name, default)


def build_score_from_metric(
    metric: Any,
    *,
    trace_id: str | None = None,
    observation_id: str | None = None,
    session_id: str | None = None,
    dataset_run_id: str | None = None,
    score_prefix: str = "eval",
    metadata: dict[str, Any] | None = None,
) -> EvaluationScore:
    """Build an EvaluationScore from a DeepEval-like metric object.

    Supported metric shapes are intentionally duck-typed: objects or dicts with
    fields such as name, score, success, reason, threshold, and evaluation_model.
    """

    metric_name = str(_metric_attr(metric, "name", "metric"))
    raw_score = _metric_attr(metric, "score", None)
    success = _metric_attr(metric, "success", None)
    value: float | str | bool
    data_type: ScoreDataType

    if isinstance(raw_score, (int, float)):
        value = float(raw_score)
        data_type = "NUMERIC"
    elif isinstance(success, bool):
        value = success
        data_type = "BOOLEAN"
    elif raw_score is not None:
        value = str(raw_score)
        data_type = "CATEGORICAL"
    else:
        value = str(success) if success is not None else "unknown"
        data_type = "CATEGORICAL"

    merged_metadata = {
        "source": "offline_evaluation",
        "metric_name": metric_name,
    }
    threshold = _metric_attr(metric, "threshold", None)
    if threshold is not None:
        merged_metadata["threshold"] = threshold
    evaluation_model = _metric_attr(metric, "evaluation_model", None) or _metric_attr(metric, "model", None)
    if evaluation_model is not None:
        merged_metadata["evaluation_model"] = str(evaluation_model)
    if metadata:
        merged_metadata.update(metadata)

    reason = _metric_attr(metric, "reason", None)
    return EvaluationScore(
        name=f"{score_prefix}.{metric_name}" if score_prefix else metric_name,
        value=value,
        data_type=data_type,
        comment=str(reason)[:1000] if reason else None,
        trace_id=trace_id,
        observation_id=observation_id,
        session_id=session_id,
        dataset_run_id=dataset_run_id,
        metadata=merged_metadata,
    )


def report_deepeval_assertion(
    *,
    metrics: Iterable[Any],
    test_case: Any | None = None,
    metadata: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Report metrics from a successful deepeval.assert_test call.

    This intentionally avoids uploading test input or actual output, as golden
    cases can contain resume/JD content. Linkage targets can be supplied by env
    variables in CI or one-off evaluation scripts.
    """

    merged_metadata: dict[str, Any] = {
        "source": "deepeval.assert_test",
    }
    current_test = os.getenv("PYTEST_CURRENT_TEST")
    if current_test:
        merged_metadata["pytest_current_test"] = current_test
    if test_case is not None:
        test_case_name = _metric_attr(test_case, "name", None)
        if test_case_name:
            merged_metadata["test_case_name"] = str(test_case_name)
    if metadata:
        merged_metadata.update(metadata)

    return report_metrics(
        metrics,
        trace_id=os.getenv("LANGFUSE_EVAL_TRACE_ID") or None,
        observation_id=os.getenv("LANGFUSE_EVAL_OBSERVATION_ID") or None,
        session_id=os.getenv("LANGFUSE_EVAL_SESSION_ID") or None,
        dataset_run_id=os.getenv("LANGFUSE_EVAL_DATASET_RUN_ID") or None,
        score_prefix=os.getenv("LANGFUSE_EVAL_SCORE_PREFIX", "eval"),
        metadata=merged_metadata,
        force=force,
    )


def report_score(score: EvaluationScore, *, force: bool = False) -> bool:
    """Report one score to Langfuse if enabled or forced."""

    if not force and not evaluation_reporting_enabled():
        return False
    return record_score(
        name=score.name,
        value=score.value,
        trace_id=score.trace_id,
        observation_id=score.observation_id,
        session_id=score.session_id,
        dataset_run_id=score.dataset_run_id,
        score_id=score.score_id,
        data_type=score.data_type,
        comment=score.comment,
        config_id=score.config_id,
        metadata=score.metadata,
    )


def report_scores(scores: Iterable[EvaluationScore], *, force: bool = False) -> dict[str, int]:
    """Report multiple scores and return a compact success summary."""

    attempted = 0
    reported = 0
    for score in scores:
        attempted += 1
        if report_score(score, force=force):
            reported += 1
    return {"attempted": attempted, "reported": reported, "failed": attempted - reported}


def report_metrics(
    metrics: Iterable[Any],
    *,
    trace_id: str | None = None,
    observation_id: str | None = None,
    session_id: str | None = None,
    dataset_run_id: str | None = None,
    score_prefix: str = "eval",
    metadata: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Convert DeepEval-like metrics to Langfuse scores and report them."""

    scores = [
        build_score_from_metric(
            metric,
            trace_id=trace_id,
            observation_id=observation_id,
            session_id=session_id,
            dataset_run_id=dataset_run_id,
            score_prefix=score_prefix,
            metadata=metadata,
        )
        for metric in metrics
    ]
    return report_scores(scores, force=force)
