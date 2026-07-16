"""SHA-256 checksum on uploaded documents

Revision ID: 0015_document_checksum
Revises: 0014_audit_purchase_decisions
Create Date: 2026-07-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015_document_checksum"
down_revision: Union[str, None] = "0014_audit_purchase_decisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("checksum_sha256", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "checksum_sha256")
