"""create project_events table for the per-project activity stream

Revision ID: 0008_project_events
Revises: 0007_create_users
Create Date: 2026-06-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_project_events"
down_revision: Union[str, None] = "0007_create_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False),
        sa.Column("tone", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("meta", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_events_project_id", "project_events", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_project_events_project_id", table_name="project_events")
    op.drop_table("project_events")
