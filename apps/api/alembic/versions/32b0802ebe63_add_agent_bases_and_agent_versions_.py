"""add agent_bases and agent_versions (AgentDefinition v2)

Revision ID: 32b0802ebe63
Revises: 8446bd5ecc2b
Create Date: 2026-03-05 09:37:14.095907

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "32b0802ebe63"
down_revision = "8446bd5ecc2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- agent_bases ---
    op.create_table(
        "agent_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Unique per workspace: stable agent key
    op.create_unique_constraint(
        "uq_agent_bases_workspace_key",
        "agent_bases",
        ["workspace_id", "key"],
    )

    op.create_index("ix_agent_bases_workspace_id", "agent_bases", ["workspace_id"])
    op.create_index("ix_agent_bases_created_by_user_id", "agent_bases", ["created_by_user_id"])
    op.create_index("ix_agent_bases_updated_at", "agent_bases", ["updated_at"])

    # --- agent_versions ---
    op.create_table(
        "agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "agent_base_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("definition_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # One version number per base
    op.create_unique_constraint(
        "uq_agent_versions_base_version",
        "agent_versions",
        ["agent_base_id", "version"],
    )

    op.create_index("ix_agent_versions_agent_base_id", "agent_versions", ["agent_base_id"])
    op.create_index("ix_agent_versions_created_by_user_id", "agent_versions", ["created_by_user_id"])
    op.create_index("ix_agent_versions_status", "agent_versions", ["status"])
    op.create_index("ix_agent_versions_created_at", "agent_versions", ["created_at"])


def downgrade() -> None:
    # Drop child first
    op.drop_index("ix_agent_versions_created_at", table_name="agent_versions")
    op.drop_index("ix_agent_versions_status", table_name="agent_versions")
    op.drop_index("ix_agent_versions_created_by_user_id", table_name="agent_versions")
    op.drop_index("ix_agent_versions_agent_base_id", table_name="agent_versions")
    op.drop_constraint("uq_agent_versions_base_version", "agent_versions", type_="unique")
    op.drop_table("agent_versions")

    # Then parent
    op.drop_index("ix_agent_bases_updated_at", table_name="agent_bases")
    op.drop_index("ix_agent_bases_created_by_user_id", table_name="agent_bases")
    op.drop_index("ix_agent_bases_workspace_id", table_name="agent_bases")
    op.drop_constraint("uq_agent_bases_workspace_key", "agent_bases", type_="unique")
    op.drop_table("agent_bases")
