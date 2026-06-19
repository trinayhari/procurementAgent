"""add quotes table for ingested supplier quotes

Revision ID: 0003_quotes
Revises: 0002_sourcing_rfqs
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_quotes"
down_revision: Union[str, None] = "0002_sourcing_rfqs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quotes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("package", sa.String(), nullable=False),
        sa.Column("package_label", sa.String(), nullable=False),
        sa.Column("rfq_id", sa.String(), nullable=True),
        sa.Column("supplier_id", sa.String(), nullable=True),
        sa.Column("supplier_name", sa.String(), nullable=False),
        sa.Column("supplier_email", sa.String(), nullable=True),
        sa.Column("material_cost", sa.Float(), nullable=True),
        sa.Column("freight", sa.Float(), nullable=True),
        sa.Column("total", sa.Float(), nullable=True),
        sa.Column("lead_days", sa.Integer(), nullable=True),
        sa.Column("delivery_date", sa.String(), nullable=True),
        sa.Column("validity", sa.String(), nullable=True),
        sa.Column("line_items", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_message_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quotes_project_id", "quotes", ["project_id"])
    op.create_index("ix_quotes_source_message_id", "quotes", ["source_message_id"])


def downgrade() -> None:
    op.drop_index("ix_quotes_source_message_id", table_name="quotes")
    op.drop_index("ix_quotes_project_id", table_name="quotes")
    op.drop_table("quotes")
