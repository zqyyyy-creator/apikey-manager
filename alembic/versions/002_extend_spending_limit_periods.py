"""Extend spending limit periods.

Revision ID: 002_limit_periods
Revises: 001_initial
Create Date: 2026-06-26
"""

from collections.abc import Sequence

from alembic import op


revision: str = "002_limit_periods"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE spending_limits "
        "MODIFY COLUMN limit_type "
        "ENUM('daily','weekly','monthly','total') NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE spending_limits "
        "MODIFY COLUMN limit_type "
        "ENUM('daily','total') NOT NULL"
    )
