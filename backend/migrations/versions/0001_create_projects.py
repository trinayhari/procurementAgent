"""create projects table

Revision ID: 0001_create_projects
Revises:
Create Date: 2026-06-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_create_projects"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("loc", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("stage_tone", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("suppliers", sa.Integer(), nullable=False),
        sa.Column("rfqs", sa.Integer(), nullable=False),
        sa.Column("quotes", sa.Integer(), nullable=False),
        sa.Column("risk", sa.String(), nullable=False),
        sa.Column("risk_tone", sa.String(), nullable=False),
        sa.Column("bar_color", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )


def downgrade() -> None:
    op.drop_table("projects")
