"""add per-user RFQ sender email

Revision ID: 0010_user_sender_email
Revises: 0009_found_supplier_relevance
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_user_sender_email"
down_revision: Union[str, None] = "0009_found_supplier_relevance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sender_email", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "sender_email")
