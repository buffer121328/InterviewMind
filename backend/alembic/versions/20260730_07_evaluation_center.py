"""Create Agent evaluation center tables.

Revision ID: 20260730_07
Revises: 20260728_05
Create Date: 2026-07-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260730_07"
down_revision: Union[str, Sequence[str], None] = "20260728_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create versioned Evaluation aggregates and audit tables."""

    op.create_table(
        "evaluation_dataset_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "name", "version", name="uq_evaluation_dataset_owner_version"
        ),
    )
    op.create_index(
        "idx_evaluation_dataset_owner_status",
        "evaluation_dataset_versions",
        ["user_id", "status"],
    )
    op.create_index(
        op.f("ix_evaluation_dataset_versions_user_id"),
        "evaluation_dataset_versions",
        ["user_id"],
    )

    op.create_table(
        "evaluation_gate_policies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("hard_gates", postgresql.JSONB(), nullable=False),
        sa.Column("metric_thresholds", postgresql.JSONB(), nullable=False),
        sa.Column("regression_tolerances", postgresql.JSONB(), nullable=False),
        sa.Column("minimum_sample_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "name", "version", name="uq_evaluation_gate_owner_version"
        ),
    )
    op.create_index(
        op.f("ix_evaluation_gate_policies_user_id"),
        "evaluation_gate_policies",
        ["user_id"],
    )

    op.create_table(
        "evaluation_suites",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("agent_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dataset_version_id", sa.String(), nullable=False),
        sa.Column("rubric_version", sa.String(length=160), nullable=False),
        sa.Column("gate_policy_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["evaluation_dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["gate_policy_id"], ["evaluation_gate_policies.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_evaluation_suite_owner_name"),
    )
    op.create_index(
        op.f("ix_evaluation_suites_user_id"), "evaluation_suites", ["user_id"]
    )

    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dataset_version_id", sa.String(), nullable=False),
        sa.Column("case_key", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("input_encrypted", sa.Text(), nullable=False),
        sa.Column("expected_encrypted", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["evaluation_dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_version_id", "case_key", name="uq_evaluation_case_dataset_key"
        ),
    )
    op.create_index(
        "idx_evaluation_case_dataset_category",
        "evaluation_cases",
        ["dataset_version_id", "category"],
    )

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("suite_id", sa.String(), nullable=False),
        sa.Column("agent_run_id", sa.String(), nullable=True),
        sa.Column("agent_name", sa.String(length=160), nullable=False),
        sa.Column("agent_version", sa.String(length=160), nullable=False),
        sa.Column("prompt_name", sa.String(length=160), nullable=True),
        sa.Column("prompt_version", sa.String(length=160), nullable=True),
        sa.Column("model_config_hash", sa.String(length=256), nullable=False),
        sa.Column("dataset_version", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("baseline_run_id", sa.String(), nullable=True),
        sa.Column("repetition_count", sa.Integer(), nullable=False),
        sa.Column("include_judges", sa.Boolean(), nullable=False),
        sa.Column("budget", postgresql.JSONB(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["baseline_run_id"], ["evaluation_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["suite_id"], ["evaluation_suites.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_evaluation_run_owner_created", "evaluation_runs", ["user_id", "created_at"]
    )
    op.create_index(
        "idx_evaluation_run_owner_status", "evaluation_runs", ["user_id", "status"]
    )
    op.create_index(op.f("ix_evaluation_runs_user_id"), "evaluation_runs", ["user_id"])

    op.create_table(
        "evaluation_case_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("evaluation_run_id", sa.String(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("repetition_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actual_output_encrypted", sa.Text(), nullable=False),
        sa.Column("record_sanitized", postgresql.JSONB(), nullable=False),
        sa.Column("trace_id", sa.String(length=256), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("token_usage", postgresql.JSONB(), nullable=False),
        sa.Column("hard_gate_passed", sa.Boolean(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("error_category", sa.String(length=160), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["evaluation_cases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"], ["evaluation_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "case_id",
            "repetition_index",
            name="uq_evaluation_case_run_repetition",
        ),
    )
    op.create_index(
        "idx_evaluation_case_run_status",
        "evaluation_case_runs",
        ["evaluation_run_id", "status"],
    )

    op.create_table(
        "evaluation_scores",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("case_run_id", sa.String(), nullable=False),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reason_sanitized", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("hard_gate", sa.Boolean(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("metric_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_run_id"], ["evaluation_case_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_run_id",
            "metric_name",
            "source",
            "metric_version",
            name="uq_evaluation_score_metric_version",
        ),
    )

    op.create_table(
        "evaluation_annotations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("case_run_id", sa.String(), nullable=False),
        sa.Column("annotator_user_id", sa.String(), nullable=False),
        sa.Column("reviewer_key", sa.String(length=120), nullable=False),
        sa.Column("blind", sa.Boolean(), nullable=False),
        sa.Column("rubric_version", sa.String(length=160), nullable=False),
        sa.Column("annotation_type", sa.String(length=32), nullable=False),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_spans", postgresql.JSONB(), nullable=False),
        sa.Column("comment_sanitized", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("adjudication", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_run_id"], ["evaluation_case_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_run_id", "revision", name="uq_evaluation_annotation_revision"
        ),
    )
    op.create_index(
        "idx_evaluation_annotation_case_metric",
        "evaluation_annotations",
        ["case_run_id", "metric_name"],
    )
    op.create_index(
        op.f("ix_evaluation_annotations_annotator_user_id"),
        "evaluation_annotations",
        ["annotator_user_id"],
    )

    op.create_table(
        "evaluation_calibrations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("judge_version", sa.String(length=160), nullable=False),
        sa.Column("dataset_version", sa.String(length=160), nullable=False),
        sa.Column("human_sample_count", sa.Integer(), nullable=False),
        sa.Column("statistics", postgresql.JSONB(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evaluation_calibrations_user_id"),
        "evaluation_calibrations",
        ["user_id"],
    )

    op.create_table(
        "evaluation_gate_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("evaluation_run_id", sa.String(), nullable=False),
        sa.Column("gate_policy_id", sa.String(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("blocked_by", postgresql.JSONB(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"], ["evaluation_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["gate_policy_id"], ["evaluation_gate_policies.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evaluation_gate_results_user_id"),
        "evaluation_gate_results",
        ["user_id"],
    )


def downgrade() -> None:
    """Drop Evaluation tables in reverse dependency order."""

    op.drop_table("evaluation_gate_results")
    op.drop_table("evaluation_calibrations")
    op.drop_table("evaluation_annotations")
    op.drop_table("evaluation_scores")
    op.drop_table("evaluation_case_runs")
    op.drop_table("evaluation_runs")
    op.drop_table("evaluation_cases")
    op.drop_table("evaluation_suites")
    op.drop_table("evaluation_gate_policies")
    op.drop_table("evaluation_dataset_versions")
