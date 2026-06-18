"""add supplier sourcing + rfq tables, project geocode cache

Revision ID: 0002_sourcing_rfqs
Revises: 0001_create_projects
Create Date: 2026-06-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_sourcing_rfqs"
down_revision: Union[str, None] = "0001_create_projects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cache the project geocode so repeated searches don't re-bill the Geocoding API.
    op.add_column("projects", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("projects", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column("projects", sa.Column("geocoded_loc", sa.String(), nullable=True))

    op.create_table(
        "found_suppliers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("package", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("distance_miles", sa.Float(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("contact_name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("website", sa.String(), nullable=True),
        sa.Column("material_categories", sa.String(), nullable=False),
        sa.Column("email_source", sa.String(), nullable=False),
        sa.Column("place_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_found_suppliers_project_id", "found_suppliers", ["project_id"]
    )

    op.create_table(
        "rfqs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("package", sa.String(), nullable=False),
        sa.Column("package_label", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("line_items", sa.Text(), nullable=False),
        sa.Column("recipients", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rfqs_project_id", "rfqs", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_rfqs_project_id", table_name="rfqs")
    op.drop_table("rfqs")
    op.drop_index("ix_found_suppliers_project_id", table_name="found_suppliers")
    op.drop_table("found_suppliers")
    op.drop_column("projects", "geocoded_loc")
    op.drop_column("projects", "lng")
    op.drop_column("projects", "lat")
