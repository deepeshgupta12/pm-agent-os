"""run scheduling tables

Revision ID: 2b78d5963ef2
Revises: 345994853b44
Create Date: 2026-03-03 11:32:51.613522

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# IMPORTANT:
# Replace these with your actual alembic identifiers:
revision = "2b78d5963ef2"
down_revision = "345994853b44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),  # agent_run | pipeline_run
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("cron", sa.String(length=120), nullable=True),
        sa.Column("interval_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_index("ix_schedules_workspace_id", "schedules", ["workspace_id"])
    op.create_index("ix_schedules_enabled_next_run_at", "schedules", ["enabled", "next_run_at"])

    op.create_table(
        "schedule_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "schedule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedules.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),  # running|success|failed
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_index("ix_schedule_runs_schedule_id", "schedule_runs", ["schedule_id"])
    op.create_index("ix_schedule_runs_started_at", "schedule_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_schedule_runs_started_at", table_name="schedule_runs")
    op.drop_index("ix_schedule_runs_schedule_id", table_name="schedule_runs")
    op.drop_table("schedule_runs")

    op.drop_index("ix_schedules_enabled_next_run_at", table_name="schedules")
    op.drop_index("ix_schedules_workspace_id", table_name="schedules")
    op.drop_table("schedules")