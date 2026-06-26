"""Initial MaaS API tables.

Revision ID: 001_initial
Revises:
Create Date: 2026-06-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


managed_key_status = sa.Enum(
    "active",
    "blocked",
    "revoked",
    name="managed_key_status",
)
spending_limit_type = sa.Enum(
    "daily",
    "weekly",
    "monthly",
    "total",
    name="spending_limit_type",
)


def upgrade() -> None:
    op.create_table(
        "client_user_mapping",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_table(
        "managed_keys",
        sa.Column("key_hash_id", sa.String(length=100), nullable=False),
        sa.Column("team_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("key_alias", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column(
            "status",
            managed_key_status,
            server_default="active",
            nullable=False,
        ),
        sa.Column("blocked_reason", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("key_hash_id"),
    )
    op.create_index("ix_managed_keys_team_id", "managed_keys", ["team_id"])
    op.create_index("ix_managed_keys_status", "managed_keys", ["status"])

    op.create_table(
        "spending_limits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key_hash_id", sa.String(length=100), nullable=False),
        sa.Column("limit_type", spending_limit_type, nullable=False),
        sa.Column("amount", sa.DECIMAL(precision=12, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="CNY", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["key_hash_id"],
            ["managed_keys.key_hash_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "key_hash_id",
            "limit_type",
            name="uq_spending_limits_key_hash_id_limit_type",
        ),
    )
    op.create_index(
        "ix_spending_limits_key_hash_id",
        "spending_limits",
        ["key_hash_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_spending_limits_key_hash_id", table_name="spending_limits")
    op.drop_table("spending_limits")
    op.drop_index("ix_managed_keys_status", table_name="managed_keys")
    op.drop_index("ix_managed_keys_team_id", table_name="managed_keys")
    op.drop_table("managed_keys")
    op.drop_table("client_user_mapping")
