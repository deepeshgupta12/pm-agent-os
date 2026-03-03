"""artifact comments mentions assignment

Revision ID: 345994853b44
Revises: 3d1d19e48a27
Create Date: 2026-03-03 11:09:27.561955

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "345994853b44"
down_revision = "3d1d19e48a27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add assignee to artifacts
    op.add_column(
        "artifacts",
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_artifacts_assigned_to_user_id", "artifacts", ["assigned_to_user_id"])
    op.create_foreign_key(
        "fk_artifacts_assigned_to_user_id_users",
        "artifacts",
        "users",
        ["assigned_to_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2) Comments
    op.create_table(
        "artifact_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_artifact_comments_artifact_id", "artifact_comments", ["artifact_id"])
    op.create_index("ix_artifact_comments_author_user_id", "artifact_comments", ["author_user_id"])

    # 3) Mentions (per comment)
    op.create_table(
        "artifact_comment_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("comment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mentioned_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mentioned_email", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["comment_id"], ["artifact_comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mentioned_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_artifact_comment_mentions_comment_id", "artifact_comment_mentions", ["comment_id"])
    op.create_index("ix_artifact_comment_mentions_mentioned_user_id", "artifact_comment_mentions", ["mentioned_user_id"])


def downgrade() -> None:
    op.drop_index("ix_artifact_comment_mentions_mentioned_user_id", table_name="artifact_comment_mentions")
    op.drop_index("ix_artifact_comment_mentions_comment_id", table_name="artifact_comment_mentions")
    op.drop_table("artifact_comment_mentions")

    op.drop_index("ix_artifact_comments_author_user_id", table_name="artifact_comments")
    op.drop_index("ix_artifact_comments_artifact_id", table_name="artifact_comments")
    op.drop_table("artifact_comments")

    op.drop_constraint("fk_artifacts_assigned_to_user_id_users", "artifacts", type_="foreignkey")
    op.drop_index("ix_artifacts_assigned_to_user_id", table_name="artifacts")
    op.drop_column("artifacts", "assigned_to_user_id")
