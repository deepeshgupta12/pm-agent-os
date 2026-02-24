"""restore retrieval fts and pgvector columns

Revision ID: REPLACE_WITH_NEW_REVISION_ID
Revises: ffe4784a0fac
Create Date: 2026-02-24

"""
from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "REPLACE_WITH_NEW_REVISION_ID"
down_revision: Union[str, None] = "ffe4784a0fac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Restore tsvector computed column + gin index if missing
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'chunks' AND column_name = 'tsv_tsvector'
            ) THEN
                ALTER TABLE chunks
                ADD COLUMN tsv_tsvector tsvector
                GENERATED ALWAYS AS (to_tsvector('english', COALESCE(text, ''))) STORED;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE tablename = 'chunks' AND indexname = 'ix_chunks_tsv_tsvector'
            ) THEN
                CREATE INDEX ix_chunks_tsv_tsvector ON chunks USING gin (tsv_tsvector);
            END IF;
        END $$;
        """
    )

    # Restore embedding_vec + indexes if missing
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'embeddings' AND column_name = 'embedding_vec'
            ) THEN
                -- requires pgvector extension (already installed)
                ALTER TABLE embeddings
                ADD COLUMN embedding_vec vector(1536);
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE tablename = 'embeddings' AND indexname = 'ix_embeddings_model'
            ) THEN
                CREATE INDEX ix_embeddings_model ON embeddings (model);
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE tablename = 'embeddings' AND indexname = 'ix_embeddings_embedding_vec'
            ) THEN
                CREATE INDEX ix_embeddings_embedding_vec
                ON embeddings USING ivfflat (embedding_vec vector_cosine_ops)
                WITH (lists = 100);
            END IF;
        END $$;
        """
    )

    # Restore sources.type index if missing
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE tablename = 'sources' AND indexname = 'ix_sources_type'
            ) THEN
                CREATE INDEX ix_sources_type ON sources (type);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Optional: keep downgrade minimal and safe
    op.execute("DROP INDEX IF EXISTS ix_sources_type;")
    op.execute("DROP INDEX IF EXISTS ix_embeddings_embedding_vec;")
    op.execute("DROP INDEX IF EXISTS ix_embeddings_model;")
    op.execute("ALTER TABLE embeddings DROP COLUMN IF EXISTS embedding_vec;")
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_tsvector;")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_tsvector;")