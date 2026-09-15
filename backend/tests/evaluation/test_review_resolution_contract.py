"""Review-resolution and calibration safety contract regression tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.db.repositories.evaluation import EvaluationRepository
from app.schemas.evaluation.evaluations import (
    EvaluationAdjudicationRequest,
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


def test_adjudication_contract_requires_a_binary_verdict() -> None:
    request = EvaluationAdjudicationRequest(
        metric_name="quality.overall", value=False, comment="证据不足"
    )
    assert request.value is False
    with pytest.raises(ValidationError):
        EvaluationAdjudicationRequest(
            metric_name="quality.overall", value="factual_omission"
        )


@pytest.mark.asyncio
async def test_failed_adjudication_rejects_case_and_refreshes_run() -> None:
    repository = EvaluationRepository()
    case_run = SimpleNamespace(
        id="case-run-1",
        evaluation_run_id="run-1",
        status="succeeded",
        hard_gate_passed=True,
        review_status="pending",
        review_resolver_key=None,
        review_resolved_at=None,
        review_resolution_note=None,
    )
    repository.get_case_run = AsyncMock(return_value=case_run)
    repository._refresh_run_review_state = AsyncMock()
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=0),
        add=Mock(),
        flush=AsyncMock(),
    )

    row = await repository.add_annotation(
        session,
        case_run_id="case-run-1",
        user_id="owner-1",
        request=EvaluationAnnotationCreateRequest(
            rubric_version="v1",
            annotation_type="binary",
            metric_name="quality.overall",
            value=False,
            reviewer_key="adjudicator",
        ),
        adjudication=True,
    )

    assert row.adjudication is True
    assert case_run.review_status == "rejected"
    repository._refresh_run_review_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_adjudication_cannot_pass_runtime_or_hard_gate_failure() -> None:
    repository = EvaluationRepository()
    repository.get_case_run = AsyncMock(
        return_value=SimpleNamespace(
            id="case-run-1",
            evaluation_run_id="run-1",
            status="failed",
            hard_gate_passed=False,
        )
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=0),
        add=Mock(),
        flush=AsyncMock(),
    )

    with pytest.raises(ValueError, match="不能通过"):
        await repository.add_annotation(
            session,
            case_run_id="case-run-1",
            user_id="owner-1",
            request=EvaluationAnnotationCreateRequest(
                rubric_version="v1",
                annotation_type="binary",
                metric_name="quality.overall",
                value=True,
                reviewer_key="adjudicator",
            ),
            adjudication=True,
        )

    session.add.assert_not_called()


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
