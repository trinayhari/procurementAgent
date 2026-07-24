"""append-only audit trail + purchase-decision (award) records

Revision ID: 0014_audit_purchase_decisions
Revises: 0013_background_jobs
Create Date: 2026-07-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014_audit_purchase_decisions"
down_revision: Union[str, None] = "0013_background_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_email", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False, server_default=""),
        sa.Column("entity_id", sa.String(), nullable=False, server_default=""),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"])

    op.create_table(
        "purchase_decisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("package", sa.String(), nullable=False),
        sa.Column("package_label", sa.String(), nullable=False, server_default=""),
        sa.Column("strategy", sa.String(), nullable=True),
        sa.Column("selections", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("supplier_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("suppliers", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("material", sa.Float(), nullable=False, server_default="0"),
        sa.Column("freight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("lead_days", sa.Integer(), nullable=True),
        sa.Column("po_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("decided_by", sa.String(), nullable=False, server_default=""),
        sa.Column("decided_by_email", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_purchase_decisions_project_id", "purchase_decisions", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_purchase_decisions_project_id", table_name="purchase_decisions")
    op.drop_table("purchase_decisions")
    op.drop_index("ix_audit_events_project_id", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_table("audit_events")
