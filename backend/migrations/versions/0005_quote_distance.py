"""add distance_miles to quotes for delivery/logistics comparison

Revision ID: 0005_quote_distance
Revises: 0004_documents
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_quote_distance"
down_revision: Union[str, None] = "0004_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("quotes", sa.Column("distance_miles", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("quotes", "distance_miles")
