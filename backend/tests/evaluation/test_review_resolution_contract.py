"""Review-resolution and calibration safety contract regression tests."""

import pytest
from pydantic import ValidationError

from app.schemas.evaluation.evaluations import (
    EvaluationCalibrationCreateRequest,
    EvaluationReviewResolutionRequest,
)
from evaluation.domain import calculate_calibration


def test_review_resolution_requires_a_non_sensitive_audit_note() -> None:
    request = EvaluationReviewResolutionRequest(
        status="approved", reviewer_key="reviewer-a", comment="确认输出与证据一致"
    )
    assert request.status == "approved"
    with pytest.raises(ValidationError, match="sensitive"):
        EvaluationReviewResolutionRequest(
            status="approved", reviewer_key="reviewer-a", comment="api_key=sk-12345678901234567890"
        )


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
