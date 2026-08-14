"""Owner-scoped cleanup must include evaluation-promotion runtime data."""

from app.domain.agent_runs import TASK_TYPE_INTERVIEW_EVALUATION_DRAFT
from scripts.cleanup_interview_data import (
    _CHECKPOINT_DELETE_STATEMENTS,
    INTERVIEW_TASK_TYPES,
)


def test_cleanup_includes_interview_evaluation_drafts_and_run_checkpoints():
    assert TASK_TYPE_INTERVIEW_EVALUATION_DRAFT in INTERVIEW_TASK_TYPES
    assert set(_CHECKPOINT_DELETE_STATEMENTS) == {
        "checkpoint_writes",
        "checkpoint_blobs",
        "checkpoints",
    }
