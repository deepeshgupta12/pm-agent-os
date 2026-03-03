"""add action_items table

Revision ID: b8c1538f9afd
Revises: 649e61e6bf18
Create Date: 2026-03-03 09:19:46.453549

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b8c1538f9afd"
down_revision: Union[str, None] = "649e61e6bf18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "action_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),

        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("title", sa.String(length=240), nullable=False, server_default=""),

        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("target_ref", sa.String(length=300), nullable=True),

        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("ix_action_items_workspace_id", "action_items", ["workspace_id"])
    op.create_index("ix_action_items_status", "action_items", ["status"])
    op.create_index("ix_action_items_type", "action_items", ["type"])
    op.create_index("ix_action_items_created_by", "action_items", ["created_by_user_id"])
    op.create_index("ix_action_items_assigned_to", "action_items", ["assigned_to_user_id"])
    op.create_index("ix_action_items_decided_by", "action_items", ["decided_by_user_id"])

    op.create_foreign_key(
        "fk_action_items_workspace",
        "action_items",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_foreign_key(
        "fk_action_items_created_by",
        "action_items",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_foreign_key(
        "fk_action_items_assigned_to",
        "action_items",
        "users",
        ["assigned_to_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_action_items_decided_by",
        "action_items",
        "users",
        ["decided_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # remove defaults for json/title after create
    op.alter_column("action_items", "payload_json", server_default=None)
    op.alter_column("action_items", "title", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_action_items_decided_by", table_name="action_items")
    op.drop_index("ix_action_items_assigned_to", table_name="action_items")
    op.drop_index("ix_action_items_created_by", table_name="action_items")
    op.drop_index("ix_action_items_type", table_name="action_items")
    op.drop_index("ix_action_items_status", table_name="action_items")
    op.drop_index("ix_action_items_workspace_id", table_name="action_items")
    op.drop_table("action_items")