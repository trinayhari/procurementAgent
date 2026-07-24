"""persist reference/display data (suppliers, dashboard, comparison, timeline, demo inbox)

Revision ID: 0006_reference_data
Revises: 0005_quote_distance
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_reference_data"
down_revision: Union[str, None] = "0005_quote_distance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("cats", sa.Text(), nullable=False),
        sa.Column("contact", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("web", sa.String(), nullable=False),
        sa.Column("rfq", sa.String(), nullable=False),
        sa.Column("rfq_tone", sa.String(), nullable=False),
        sa.Column("last", sa.String(), nullable=False),
        sa.Column("quotes", sa.String(), nullable=False),
        sa.Column("quote_val", sa.String(), nullable=False),
        sa.Column("lead", sa.String(), nullable=False),
        sa.Column("logo", sa.String(), nullable=False),
        sa.Column("logo_bg", sa.String(), nullable=False),
        sa.Column("fin", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )

    op.create_table(
        "supplier_comms",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("tone", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("time", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "dashboard_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("delta", sa.String(), nullable=False),
        sa.Column("sub", sa.String(), nullable=False),
        sa.Column("up", sa.Boolean(), nullable=False),
        sa.Column("down", sa.Boolean(), nullable=False),
        sa.Column("ai", sa.Boolean(), nullable=False),
        sa.Column("risk", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "activity_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False),
        sa.Column("tone", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("meta", sa.String(), nullable=False),
        sa.Column("time", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "overview_cards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("sub", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False),
        sa.Column("tone", sa.String(), nullable=False),
        sa.Column("ai", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "packages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("pct", sa.Integer(), nullable=False),
        sa.Column("tone", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "line_item_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("group", sa.String(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("tone", sa.String(), nullable=False),
        sa.Column("items", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "comparisons",
        sa.Column("pkg", sa.String(), nullable=False),
        sa.Column("suppliers", sa.Text(), nullable=False),
        sa.Column("rows", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.String(), nullable=False),
        sa.Column("reasons", sa.Text(), nullable=False),
        sa.Column("savings", sa.String(), nullable=False),
        sa.Column("savings_note", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("pkg"),
    )

    op.create_table(
        "milestones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("desc", sa.String(), nullable=False),
        sa.Column("tone", sa.String(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "gantt_bars",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("length", sa.Integer(), nullable=False),
        sa.Column("tone", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("warn", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "gantt_columns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "rfq_folders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("count", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "demo_rfqs",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("sup", sa.String(), nullable=False),
        sa.Column("pkg", sa.String(), nullable=False),
        sa.Column("folder", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("status_tone", sa.String(), nullable=False),
        sa.Column("preview", sa.String(), nullable=False),
        sa.Column("time", sa.String(), nullable=False),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.Column("logo", sa.String(), nullable=False),
        sa.Column("logo_bg", sa.String(), nullable=False),
        sa.Column("thread", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )

    op.create_table(
        "demo_quotes",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("sup", sa.String(), nullable=False),
        sa.Column("pkg", sa.String(), nullable=False),
        sa.Column("amount", sa.String(), nullable=False),
        sa.Column("freight", sa.String(), nullable=False),
        sa.Column("total", sa.String(), nullable=False),
        sa.Column("lead", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("logo", sa.String(), nullable=False),
        sa.Column("logo_bg", sa.String(), nullable=False),
        sa.Column("best", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )


def downgrade() -> None:
    for table in (
        "demo_quotes",
        "demo_rfqs",
        "rfq_folders",
        "gantt_columns",
        "gantt_bars",
        "milestones",
        "comparisons",
        "line_item_groups",
        "packages",
        "overview_cards",
        "activity_items",
        "dashboard_metrics",
        "supplier_comms",
        "suppliers",
    ):
        op.drop_table(table)
