"""add workspace template_admin_json

Revision ID: 649e61e6bf18
Revises: 58d38c06f429
Create Date: 2026-03-02 16:55:17.097558

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '649e61e6bf18'
down_revision: Union[str, None] = '58d38c06f429'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "template_admin_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("workspaces", "template_admin_json", server_default=None)

def downgrade() -> None:
    op.drop_column("workspaces", "template_admin_json")
