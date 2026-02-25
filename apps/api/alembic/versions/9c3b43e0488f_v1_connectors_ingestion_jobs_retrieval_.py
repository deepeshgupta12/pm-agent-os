"""v1 connectors + ingestion jobs + retrieval trace

Revision ID: 9c3b43e0488f
Revises: b11bd96c14d3
Create Date: 2026-02-25

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9c3b43e0488f"
down_revision = "b11bd96c14d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----------------------------
    # connectors (workspace-level)
    # ----------------------------
    op.create_table(
        "connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,  # auto-creates ix_connectors_workspace_id
        ),
        sa.Column("type", sa.String(length=32), nullable=False),  # docs|jira|github|slack|support|analytics
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="disconnected"),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("workspace_id", "type", "name", name="uq_connectors_ws_type_name"),
    )
    # IMPORTANT: do NOT create ix_connectors_workspace_id manually (it already exists from index=True)
    op.create_index("ix_connectors_workspace_type", "connectors", ["workspace_id", "type"])

    # -----------------------------------------
    # ingestion_jobs (auditable ingestion runs)
    # -----------------------------------------
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,  # auto-creates ix_ingestion_jobs_workspace_id
        ),
        sa.Column(
            "connector_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connectors.id", ondelete="SET NULL"),
            nullable=True,
            index=True,  # auto-creates ix_ingestion_jobs_connector_id
        ),
        # optional link to retrieval_sources row (table name is "sources" in retrieval_models)
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
            index=True,  # auto-creates ix_ingestion_jobs_source_id
        ),
        sa.Column(
            "kind",
            sa.String(length=64),
            nullable=False,
            server_default="manual",
        ),  # docs_sync|jira_sync|manual_ingest
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="queued",
        ),  # queued|running|success|failed
        sa.Column(
            "timeframe",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,  # auto-creates ix_ingestion_jobs_created_by_user_id
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    # IMPORTANT: do NOT manually create indexes that already exist from index=True

    # ---------------------------------------------
    # retrieval_requests (traceability per query)
    # ---------------------------------------------
    op.create_table(
        "retrieval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,  # auto-creates ix_retrieval_requests_workspace_id
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,  # auto-creates ix_retrieval_requests_created_by_user_id
        ),
        sa.Column("q", sa.String(length=500), nullable=False),
        sa.Column("k", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("alpha", sa.Float(), nullable=False, server_default="0.65"),
        sa.Column("source_types", sa.String(length=300), nullable=True),  # comma-separated
        sa.Column(
            "timeframe",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    # Keep this one: not auto-created
    op.create_index("ix_retrieval_requests_created_at", "retrieval_requests", ["created_at"])

    # -----------------------------------------------------
    # retrieval_request_items (traceability per result row)
    # -----------------------------------------------------
    op.create_table(
        "retrieval_request_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("retrieval_requests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,  # auto-creates ix_retrieval_request_items_request_id
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
            nullable=True,
            index=True,  # auto-creates ix_retrieval_request_items_chunk_id
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
            index=True,  # auto-creates ix_retrieval_request_items_document_id
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
            index=True,  # auto-creates ix_retrieval_request_items_source_id
        ),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("score_fts", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score_vec", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score_hybrid", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    # IMPORTANT: do NOT manually create indexes that already exist from index=True


def downgrade() -> None:
    # Drop tables (indexes created via index=True are dropped automatically with table)
    op.drop_table("retrieval_request_items")

    op.drop_index("ix_retrieval_requests_created_at", table_name="retrieval_requests")
    op.drop_table("retrieval_requests")

    op.drop_table("ingestion_jobs")

    op.drop_index("ix_connectors_workspace_type", table_name="connectors")
    op.drop_table("connectors")