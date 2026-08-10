"""scope supplier_comms to a supplier (add supplier_comms.supplier_id)

Revision ID: 0017_supplier_comm_supplier_id
Revises: 0016_user_cc_email
Create Date: 2026-08-09

The communication-history timeline used to be a single global list shown
identically for every supplier. It is now per-supplier via a required
`supplier_id` FK. The existing rows are seed-only demo data with no supplier
linkage, so they're cleared here and re-seeded per-supplier on next startup
(seed_suppliers repopulates when the table is empty).

batch_alter_table so this works on SQLite (local dev) as well as Postgres (prod).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017_supplier_comm_supplier_id"
down_revision: Union[str, None] = "0016_user_cc_email"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Old rows carry no supplier linkage; drop them so the non-null column can be
    # added cleanly, then let seed_suppliers re-populate per supplier on boot.
    op.execute("DELETE FROM supplier_comms")
    with op.batch_alter_table("supplier_comms") as batch_op:
        batch_op.add_column(sa.Column("supplier_id", sa.String(), nullable=False))
        batch_op.create_index(
            "ix_supplier_comms_supplier_id", ["supplier_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_supplier_comms_supplier_id",
            "suppliers",
            ["supplier_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("supplier_comms") as batch_op:
        batch_op.drop_constraint("fk_supplier_comms_supplier_id", type_="foreignkey")
        batch_op.drop_index("ix_supplier_comms_supplier_id")
        batch_op.drop_column("supplier_id")
