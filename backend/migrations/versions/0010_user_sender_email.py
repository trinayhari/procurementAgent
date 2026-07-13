"""add per-user RFQ sender email

Revision ID: 0010_user_sender_email
Revises: 0011_timeline_events
Create Date: 2026-07-10

Chained after 0011 (which landed on main first, also revising 0009) so the
migration history keeps a single head.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_user_sender_email"
down_revision: Union[str, None] = "0011_timeline_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sender_email", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "sender_email")
