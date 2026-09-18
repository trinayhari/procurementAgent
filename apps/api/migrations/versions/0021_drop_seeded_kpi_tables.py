"""drop the seeded dashboard_metrics / overview_cards / packages tables

Revision ID: 0021_drop_seeded_kpi_tables
Revises: 0020_rfq_kind_attachments
Create Date: 2026-09-17

Dashboard KPIs, project overview cards and per-package progress are now
computed from each organization's real projects, documents, RFQs, quotes and
purchase decisions (app/services/metrics.py). The three tables held only the
prototype's literals — identical on every project of every tenant and
contradicting the real-data checklist beside them — so they go away entirely.
No user data lives in them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021_drop_seeded_kpi_tables"
down_revision: Union[str, None] = "0020_rfq_kind_attachments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("packages", "overview_cards", "dashboard_metrics"):
        op.drop_table(table)


def downgrade() -> None:
    # Recreated empty (as in 0006); nothing seeds them any more.
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
