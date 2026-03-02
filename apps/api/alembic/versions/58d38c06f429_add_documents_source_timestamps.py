from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "58d38c06f429"
down_revision = "07e82f73e7e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_documents_source_created_at", "documents", ["source_created_at"])
    op.create_index("ix_documents_source_updated_at", "documents", ["source_updated_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_source_updated_at", table_name="documents")
    op.drop_index("ix_documents_source_created_at", table_name="documents")

    op.drop_column("documents", "source_updated_at")
    op.drop_column("documents", "source_created_at")