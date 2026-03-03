"""approvals v2 policy + action decisions

Revision ID: 3d1d19e48a27
Revises: b8c1538f9afd
Create Date: 2026-03-03 09:34:57.185090

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "3d1d19e48a27"
down_revision = "b8c1538f9afd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) workspace approvals policy store
    op.add_column(
        "workspaces",
        sa.Column(
            "approvals_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("workspaces", "approvals_json", server_default=None)

    # 2) snapshot approvals_required on action_items
    op.add_column(
        "action_items",
        sa.Column("approvals_required", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("action_items", "approvals_required", server_default=None)

    # 3) action decisions table (auditable)
    op.create_table(
        "action_item_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("action_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "reviewer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("decision", sa.String(length=16), nullable=False),  # approved|rejected
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("action_id", "reviewer_user_id", name="uq_action_reviewer_once"),
    )


def downgrade() -> None:
    op.drop_table("action_item_decisions")
    op.drop_column("action_items", "approvals_required")
    op.drop_column("workspaces", "approvals_json")
