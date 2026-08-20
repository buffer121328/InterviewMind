"""Regression contracts for legacy evaluation annotation schema repair migrations."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.mark.fast
@pytest.mark.parametrize(
    ("filename", "column", "backfill"),
    [
        (
            "20260820_20_repair_evaluation_annotation_reviewer_key.py",
            "reviewer_key VARCHAR(120)",
            "SET reviewer_key = 'reviewer-default'",
        ),
        (
            "20260820_21_repair_evaluation_annotation_blind.py",
            "blind BOOLEAN",
            "SET blind = TRUE",
        ),
    ],
)
def test_annotation_schema_repair_migrations_are_idempotent_and_backfill(
    filename: str, column: str, backfill: str
) -> None:
    """Legacy detail reads regain each annotation field required by the ORM."""

    migration_path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("evaluation_annotation_repair", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements: list[str] = []

    original_execute = migration.op.execute
    migration.op.execute = lambda statement: statements.append(str(statement))
    try:
        migration.upgrade()
        migration.downgrade()
    finally:
        migration.op.execute = original_execute

    upgrade, downgrade = statements
    assert f"ADD COLUMN IF NOT EXISTS {column}" in upgrade
    assert backfill in upgrade
    assert f"ALTER COLUMN {column.split()[0]} SET NOT NULL" in upgrade
    assert f"DROP COLUMN IF EXISTS {column.split()[0]}" in downgrade
