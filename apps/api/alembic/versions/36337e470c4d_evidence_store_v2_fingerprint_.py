"""evidence store v2: fingerprint + normalized ids

Revision ID: 36337e470c4d
Revises: 32b0802ebe63
Create Date: 2026-03-11 11:44:27.239354

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "36337e470c4d"
down_revision = "32b0802ebe63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add columns (nullable first for safe backfill)
    op.add_column("evidence", sa.Column("fingerprint", sa.String(length=32), nullable=True))
    op.add_column("evidence", sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("evidence", sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("evidence", sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True))

    # 2) Backfill fingerprint for existing rows using a stable hash
    # Use md5 over (source_ref + "\n" + excerpt). 32 chars.
    op.execute(
        sa.text(
            """
            UPDATE evidence
            SET fingerprint = md5(COALESCE(source_ref, '') || E'\\n' || COALESCE(excerpt, ''))
            WHERE fingerprint IS NULL
            """
        )
    )

    # 3) Set NOT NULL after backfill
    op.alter_column("evidence", "fingerprint", existing_type=sa.String(length=32), nullable=False)

    # 4) Add FK constraints (SET NULL so evidence stays even if upstream doc/chunk removed)
    op.create_foreign_key(
        "fk_evidence_source_id_sources",
        "evidence",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_evidence_document_id_documents",
        "evidence",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_evidence_chunk_id_chunks",
        "evidence",
        "chunks",
        ["chunk_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 5) Dedupe enforcement: a run cannot have same evidence twice
    op.create_index(
        "ix_evidence_run_fingerprint_unique",
        "evidence",
        ["run_id", "fingerprint"],
        unique=True,
    )

    # Helpful query indexes
    op.create_index("ix_evidence_source_id", "evidence", ["source_id"], unique=False)
    op.create_index("ix_evidence_document_id", "evidence", ["document_id"], unique=False)
    op.create_index("ix_evidence_chunk_id", "evidence", ["chunk_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_evidence_chunk_id", table_name="evidence")
    op.drop_index("ix_evidence_document_id", table_name="evidence")
    op.drop_index("ix_evidence_source_id", table_name="evidence")
    op.drop_index("ix_evidence_run_fingerprint_unique", table_name="evidence")

    op.drop_constraint("fk_evidence_chunk_id_chunks", "evidence", type_="foreignkey")
    op.drop_constraint("fk_evidence_document_id_documents", "evidence", type_="foreignkey")
    op.drop_constraint("fk_evidence_source_id_sources", "evidence", type_="foreignkey")

    op.drop_column("evidence", "chunk_id")
    op.drop_column("evidence", "document_id")
    op.drop_column("evidence", "source_id")
    op.drop_column("evidence", "fingerprint")