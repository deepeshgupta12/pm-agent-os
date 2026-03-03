"""v3 governance policy rbac + agent v2 tables

Revision ID: 3516d58727cb
Revises: 2b78d5963ef2
Create Date: 2026-03-03 15:29:16.916504

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "3516d58727cb"
down_revision = "2b78d5963ef2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------
    # 1) Workspace governance store
    # -----------------------------
    op.add_column(
        "workspaces",
        sa.Column(
            "policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("workspaces", "policy_json", server_default=None)

    op.add_column(
        "workspaces",
        sa.Column(
            "rbac_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("workspaces", "rbac_json", server_default=None)

    # -----------------------------
    # 2) AgentDefinition v2 tables
    # -----------------------------
    op.create_table(
        "agent_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "key", name="uq_agent_bases_workspace_key"),
    )

    # keep updated_at fresh on UPDATE (Postgres trigger would be nicer, but we stay consistent with app-side onupdate)
    # In migrations we won't create triggers; SQLAlchemy onupdate handles it.

    op.create_table(
        "agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_base_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_bases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),  # draft|published|archived
        sa.Column(
            "definition_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("agent_base_id", "version", name="uq_agent_versions_base_version"),
    )

    op.alter_column("agent_versions", "definition_json", server_default=None)
    op.alter_column("agent_versions", "status", server_default=None)


def downgrade() -> None:
    op.drop_table("agent_versions")
    op.drop_table("agent_bases")
    op.drop_column("workspaces", "rbac_json")
    op.drop_column("workspaces", "policy_json")
