"""create timeline_events table for extracted project schedules

Revision ID: 0011_timeline_events
Revises: 0009_found_supplier_relevance
Create Date: 2026-07-10

Note: numbered 0011 because 0010_user_sender_email exists on the PRO-12 branch.
Both revise 0009 until one of them merges; if PRO-12 lands first, point
down_revision here at "0010_user_sender_email" to keep a single head.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_timeline_events"
down_revision: Union[str, None] = "0009_found_supplier_relevance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timeline_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("start", sa.String(), nullable=False),
        sa.Column("end", sa.String(), nullable=False),
        sa.Column("date_text", sa.String(), nullable=False),
        sa.Column("desc", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_doc", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_timeline_events_project_id", "timeline_events", ["project_id"])
    op.create_index("ix_timeline_events_document_id", "timeline_events", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_timeline_events_document_id", table_name="timeline_events")
    op.drop_index("ix_timeline_events_project_id", table_name="timeline_events")
    op.drop_table("timeline_events")
