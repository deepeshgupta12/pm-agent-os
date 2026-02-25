from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision = "ea4deb5ffa52"
down_revision = "4925b80cccec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_run_logs_run_id", "run_logs", ["run_id"])
    op.create_index("ix_run_logs_created_at", "run_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_run_logs_created_at", table_name="run_logs")
    op.drop_index("ix_run_logs_run_id", table_name="run_logs")
    op.drop_table("run_logs")