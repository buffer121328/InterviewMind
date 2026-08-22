"""Review-resolution and calibration safety contract regression tests."""

import pytest
from pydantic import ValidationError

from app.schemas.evaluation.evaluations import (
    EvaluationAnnotationCreateRequest,
    EvaluationCalibrationCreateRequest,
    EvaluationReviewResolutionRequest,
)
from evaluation.domain import calculate_calibration
from evaluation.baselines import build_baseline_comparison


def test_review_resolution_requires_a_non_sensitive_audit_note() -> None:
    request = EvaluationReviewResolutionRequest(
        status="approved", reviewer_key="reviewer-a", comment="确认输出与证据一致"
    )
    assert request.status == "approved"
    with pytest.raises(ValidationError, match="sensitive"):
        EvaluationReviewResolutionRequest(
            status="approved", reviewer_key="reviewer-a", comment="api_key=sk-12345678901234567890"
        )


def test_new_annotations_default_to_the_single_owner_expert() -> None:
    request = EvaluationAnnotationCreateRequest(
        rubric_version="v1",
        annotation_type="binary",
        metric_name="quality.overall",
        value=True,
    )
    assert request.reviewer_key == "owner-expert"
    assert request.blind is False


def test_calibration_rejects_severe_flags_on_human_negative_cases() -> None:
    with pytest.raises(ValidationError, match="human-confirmed positive"):
        EvaluationCalibrationCreateRequest(
            metric_name="judge.quality", judge_version="v1", dataset_version="v1",
            judge_scores=[0.1, 0.9], human_scores=[0.0, 1.0],
            judge_binary=[False, True], human_binary=[False, True], severe_mask=[True, False],
        )


def test_severe_miss_requires_a_human_positive_case() -> None:
    result = calculate_calibration(
        judge_scores=[0.1, 0.1], human_scores=[0.0, 1.0],
        judge_binary=[False, False], human_binary=[False, True], severe_mask=[False, True],
    )
    assert result.severe_error_miss_rate == 1.0


def test_resolved_pending_review_no_longer_creates_a_baseline_regression() -> None:
    baseline = {
        "run_id": "baseline-1",
        "dataset_version": "builtin.interview-planner.release:v1",
        "agent_name": "interview_planner",
        "model_config_hash": "sha256:model",
        "summary": {
            "complete_success_rate": 1.0,
            "p95_latency_ms": 80.0,
            "token_total": 0,
            "metrics": {"governance.pending_review_rate": 0.0},
        },
    }
    comparison = build_baseline_comparison(
        current_summary={
            "complete_success_rate": 1.0,
            "p95_latency_ms": 80.0,
            "token_total": 0,
            "metrics": {"governance.pending_review_rate": 0.0},
        },
        current_dataset_version="builtin.interview-planner.release:v1",
        current_agent_name="interview_planner",
        current_model_config_hash="sha256:model",
        baseline_snapshot=baseline,
    )

    assert comparison["metric_deltas"] == {"governance.pending_review_rate": 0.0}
    assert comparison["regression_count"] == 0
