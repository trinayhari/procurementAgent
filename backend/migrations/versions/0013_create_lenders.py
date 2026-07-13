"""create lenders table (project financing contacts, PRO-16)

Revision ID: 0013_create_lenders
Revises: 0012_timeline_event_done
Create Date: 2026-07-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013_create_lenders"
down_revision: Union[str, None] = "0012_timeline_event_done"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lenders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("institution", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lenders_project_id", "lenders", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_lenders_project_id", table_name="lenders")
    op.drop_table("lenders")
