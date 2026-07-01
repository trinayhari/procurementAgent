"""add relevance_score and verify_reason to found_suppliers

Revision ID: 0009_found_supplier_relevance
Revises: 0008_project_events
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_found_supplier_relevance"
down_revision: Union[str, None] = "0008_project_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "found_suppliers",
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "found_suppliers",
        sa.Column("verify_reason", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("found_suppliers", "verify_reason")
    op.drop_column("found_suppliers", "relevance_score")
