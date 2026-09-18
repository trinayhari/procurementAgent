"""drop the seeded project display columns and the demo_quotes table

Revision ID: 0023_computed_project_rows
Revises: 0022_package_budgets
Create Date: 2026-09-17

A project row's stage, procurement %, supplier / RFQ / quote counts and risk
were seeded literals (identical forever: "Highway 50 · 8 RFQs · 2 quotes ·
High" with no data behind them) and never updated for new projects. They are
now computed from the project's own rows (app/services/metrics.py
project_rollups); risk had no honest derivation and is dropped from the API.
The demo_quotes table backed a fallback that served Riverside's quotes under
every other demo project; it is removed with the fallback.

batch_alter_table so the column drops work on SQLite as well as Postgres.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023_computed_project_rows"
down_revision: Union[str, None] = "0022_package_budgets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DROPPED = ("stage", "stage_tone", "progress", "suppliers", "rfqs", "quotes", "risk", "risk_tone", "bar_color")


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        for col in _DROPPED:
            batch_op.drop_column(col)
    op.drop_table("demo_quotes")


def downgrade() -> None:
    # Recreated with neutral defaults; nothing seeds them any more.
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("stage", sa.String(), nullable=False, server_default="Plans Review"))
        batch_op.add_column(sa.Column("stage_tone", sa.String(), nullable=False, server_default="gray"))
        batch_op.add_column(sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("suppliers", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("rfqs", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("quotes", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("risk", sa.String(), nullable=False, server_default="Low"))
        batch_op.add_column(sa.Column("risk_tone", sa.String(), nullable=False, server_default="success"))
        batch_op.add_column(sa.Column("bar_color", sa.String(), nullable=False, server_default="var(--primary)"))
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
