"""Merge evaluation center and question cleanup migration heads.

Revision ID: 20260730_08
Revises: 20260728_06, 20260730_07
Create Date: 2026-07-30
"""

from typing import Sequence, Union


revision: str = "20260730_08"
down_revision: Union[str, Sequence[str], None] = (
    "20260728_06",
    "20260730_07",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge both already-defined migration branches without additional DDL."""


def downgrade() -> None:
    """Split the merge point without reverting either parent migration."""
