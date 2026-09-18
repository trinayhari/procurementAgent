"""rfqs.kind + rfqs.attachments

Revision ID: 0020_rfq_kind_attachments
Revises: 0019_supplier_comm_supplier_id
Create Date: 2026-08-09

Two additions to support subcontractor bid requests and user-selected email
attachments:

- `kind`: "materials" (BOM-driven quote request) or "subcontractor"
  (scope-of-work bid request). Server-set at generate time; every pre-existing
  RFQ is a materials RFQ, so the default backfills history correctly.
- `attachments`: JSON list of {"documentId", "name"} — project documents the
  user chose to attach to the outgoing email, denormalized like `recipients`.

batch_alter_table so this works on SQLite (local dev) as well as Postgres (prod).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020_rfq_kind_attachments"
down_revision: Union[str, None] = "0019_supplier_comm_supplier_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.String(), nullable=False, server_default="materials")
        )
        batch_op.add_column(
            sa.Column("attachments", sa.Text(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.drop_column("attachments")
        batch_op.drop_column("kind")
