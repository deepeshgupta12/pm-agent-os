"""v3 governance events audit log

Revision ID: 8446bd5ecc2b
Revises: 3516d58727cb
Create Date: 2026-03-03 16:25:06.560551

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8446bd5ecc2b"
down_revision = "3516d58727cb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "governance_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),  # allow|deny
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.alter_column("governance_events", "meta", server_default=None)
    op.alter_column("governance_events", "reason", server_default=None)

    op.create_index("ix_governance_events_workspace_created_at", "governance_events", ["workspace_id", "created_at"])
    op.create_index("ix_governance_events_action", "governance_events", ["action"])
    op.create_index("ix_governance_events_decision", "governance_events", ["decision"])


def downgrade() -> None:
    op.drop_index("ix_governance_events_decision", table_name="governance_events")
    op.drop_index("ix_governance_events_action", table_name="governance_events")
    op.drop_index("ix_governance_events_workspace_created_at", table_name="governance_events")
    op.drop_table("governance_events")