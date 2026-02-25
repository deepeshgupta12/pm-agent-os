"""add artifact reviews for approvals

Revision ID: b11bd96c14d3
Revises: ea4deb5ffa52
Create Date: 2026-02-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# IMPORTANT: replace these with actual IDs from your generated file
revision = "b11bd96c14d3"
down_revision = "ea4deb5ffa52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="requested"),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("request_comment", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
    )

    op.create_index("ix_artifact_reviews_artifact_id", "artifact_reviews", ["artifact_id"])
    op.create_index("ix_artifact_reviews_requested_by_user_id", "artifact_reviews", ["requested_by_user_id"])
    op.create_index("ix_artifact_reviews_decided_by_user_id", "artifact_reviews", ["decided_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_artifact_reviews_decided_by_user_id", table_name="artifact_reviews")
    op.drop_index("ix_artifact_reviews_requested_by_user_id", table_name="artifact_reviews")
    op.drop_index("ix_artifact_reviews_artifact_id", table_name="artifact_reviews")
    op.drop_table("artifact_reviews")