"""enforce single pipeline_prev_artifact evidence per run

Revision ID: f0e35627c430
Revises: 517e08771069
Create Date: 2026-02-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f0e35627c430"
down_revision: Union[str, None] = "517e08771069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "ux_evidence_run_pipeline_prev_artifact"


def upgrade() -> None:
    # 1) De-dupe any existing duplicates safely (keep newest by created_at)
    # Only applies to source_name='pipeline_prev_artifact'
    op.execute(
        """
        WITH ranked AS (
          SELECT
            id,
            run_id,
            created_at,
            ROW_NUMBER() OVER (
              PARTITION BY run_id
              ORDER BY created_at DESC, id DESC
            ) AS rn
          FROM evidence
          WHERE source_name = 'pipeline_prev_artifact'
        )
        DELETE FROM evidence e
        USING ranked r
        WHERE e.id = r.id
          AND r.rn > 1;
        """
    )

    # 2) Add partial unique index:
    #    exactly one pipeline_prev_artifact evidence row per run
    op.create_index(
        INDEX_NAME,
        "evidence",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("source_name = 'pipeline_prev_artifact'"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="evidence")