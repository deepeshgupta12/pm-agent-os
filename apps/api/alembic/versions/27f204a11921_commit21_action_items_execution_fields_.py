"""commit21 action_items execution fields for approval gated writes

Revision ID: 27f204a11921
Revises: 36337e470c4d
Create Date: 2026-03-11 16:28:58.791906

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "27f204a11921"
down_revision = "36337e470c4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "action_items",
        sa.Column("execution_status", sa.String(length=24), nullable=False, server_default="not_started"),
    )
    op.add_column(
        "action_items",
        sa.Column("execution_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "action_items",
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "action_items",
        sa.Column("execution_finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "action_items",
        sa.Column("execution_last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "action_items",
        sa.Column("execution_idempotency_key", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "action_items",
        sa.Column(
            "execution_result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # indexes
    op.create_index("ix_action_items_execution_status", "action_items", ["execution_status"])
    op.create_index("ix_action_items_execution_idempotency_key", "action_items", ["execution_idempotency_key"])

    # drop server defaults so app controls future writes cleanly
    op.alter_column("action_items", "execution_status", server_default=None)
    op.alter_column("action_items", "execution_attempts", server_default=None)
    op.alter_column("action_items", "execution_result_json", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_action_items_execution_idempotency_key", table_name="action_items")
    op.drop_index("ix_action_items_execution_status", table_name="action_items")

    op.drop_column("action_items", "execution_result_json")
    op.drop_column("action_items", "execution_idempotency_key")
    op.drop_column("action_items", "execution_last_error")
    op.drop_column("action_items", "execution_finished_at")
    op.drop_column("action_items", "execution_started_at")
    op.drop_column("action_items", "execution_attempts")
    op.drop_column("action_items", "execution_status")