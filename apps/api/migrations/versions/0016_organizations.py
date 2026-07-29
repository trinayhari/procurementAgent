"""organizations table + organization_id on every tenant-scoped table

Adds the tenant boundary. Existing rows are backfilled to a single `default`
organization so a deployment that already has data keeps its current (shared)
behaviour rather than orphaning every project; new signups each get their own.

Revision ID: 0016_organizations
Revises: 0015_document_checksum
Create Date: 2026-07-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_organizations"
down_revision: Union[str, None] = "0015_document_checksum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The id/name of the organization every pre-existing row is backfilled into.
DEFAULT_ORG_ID = "default"
DEFAULT_ORG_NAME = "Default Organization"

# Every tenant-scoped table. The reference/display tables (dashboard_metrics,
# activity_items, overview_cards, packages, line_item_groups, comparisons,
# milestones, gantt_bars, gantt_columns, rfq_folders, demo_rfqs, demo_quotes)
# and supplier_comms are deliberately excluded: they hold only seeded literals
# shared identically by every tenant.
SCOPED_TABLES = (
    "users",
    "projects",
    "documents",
    "suppliers",
    "rfqs",
    "quotes",
    "found_suppliers",
    "timeline_events",
    "project_events",
    "purchase_decisions",
    "audit_events",
    "background_jobs",
    "lenders",
)


def _index_name(table: str) -> str:
    return f"ix_{table}_organization_id"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )

    # One row so the backfill below has somewhere to land.
    organizations = sa.table(
        "organizations",
        sa.column("seq", sa.Integer),
        sa.column("id", sa.String),
        sa.column("name", sa.String),
    )
    op.bulk_insert(
        organizations, [{"seq": 1, "id": DEFAULT_ORG_ID, "name": DEFAULT_ORG_NAME}]
    )

    for table in SCOPED_TABLES:
        # Add nullable, backfill, then tighten to NOT NULL — a NOT NULL column
        # can't be added to a table that already has rows.
        op.add_column(table, sa.Column("organization_id", sa.String(), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {table} SET organization_id = :org WHERE organization_id IS NULL"
            ).bindparams(org=DEFAULT_ORG_ID)
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column("organization_id", existing_type=sa.String(), nullable=False)
        op.create_index(_index_name(table), table, ["organization_id"])


def downgrade() -> None:
    for table in reversed(SCOPED_TABLES):
        op.drop_index(_index_name(table), table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("organization_id")
    op.drop_table("organizations")
