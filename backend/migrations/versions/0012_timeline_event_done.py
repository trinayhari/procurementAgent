"""add human check-off (done/done_at) to timeline events

Revision ID: 0012_timeline_event_done
Revises: 0011_timeline_events
Create Date: 2026-07-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_timeline_event_done"
down_revision: Union[str, None] = "0011_timeline_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "timeline_events",
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "timeline_events",
        sa.Column("done_at", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("timeline_events", "done_at")
    op.drop_column("timeline_events", "done")
