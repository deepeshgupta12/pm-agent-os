"""add retrieval store (sources documents chunks embeddings)

Revision ID: 3b0c91a6fb4a
Revises: abe0738163f9
Create Date: 24 February 2026
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "3b0c91a6fb4a"
down_revision = "abe0738163f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # --- sources ---
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sources_workspace_id", "sources", ["workspace_id"])
    op.create_index("ix_sources_type", "sources", ["type"])

    # --- documents ---
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False, server_default="Untitled"),
        sa.Column("raw_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])
    op.create_index("ix_documents_source_id", "documents", ["source_id"])
    op.create_index("ix_documents_external_id", "documents", ["external_id"])

    # --- chunks ---
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    # Add GENERATED tsvector column for keyword search + GIN index
    op.execute(
        """
        ALTER TABLE chunks
        ADD COLUMN IF NOT EXISTS tsv_tsvector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_tsv_tsvector ON chunks USING GIN (tsv_tsvector);")

    # --- embeddings ---
    op.create_table(
        "embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chunks.id"), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_embeddings_chunk_id", "embeddings", ["chunk_id"])
    op.create_index("ix_embeddings_model", "embeddings", ["model"])

    # Add vector column + ivfflat index (cosine)
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS embedding_vec vector(1536);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_embedding_vec "
        "ON embeddings USING ivfflat (embedding_vec vector_cosine_ops) WITH (lists = 100);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_embeddings_embedding_vec;")
    op.execute("ALTER TABLE embeddings DROP COLUMN IF EXISTS embedding_vec;")

    op.drop_index("ix_embeddings_model", table_name="embeddings")
    op.drop_index("ix_embeddings_chunk_id", table_name="embeddings")
    op.drop_table("embeddings")

    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_tsvector;")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_tsvector;")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_documents_external_id", table_name="documents")
    op.drop_index("ix_documents_source_id", table_name="documents")
    op.drop_index("ix_documents_workspace_id", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_sources_type", table_name="sources")
    op.drop_index("ix_sources_workspace_id", table_name="sources")
    op.drop_table("sources")