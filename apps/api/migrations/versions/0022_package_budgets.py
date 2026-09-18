"""package_budgets — an optional budget per (organization, project, package)

Revision ID: 0022_package_budgets
Revises: 0021_drop_seeded_kpi_tables
Create Date: 2026-09-17

The Quote Comparison screen used to compare every award against a hard-coded
sample budget per category, so a fresh organization saw "$711,481 over
budget" on its first comparison. Budgets are now real, optional, and set by the
user per package; a preset category, custom BOM or trade scope has no single
row of its own, hence a small keyed table rather than a column.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022_package_budgets"
down_revision: Union[str, None] = "0021_drop_seeded_kpi_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "package_budgets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("package", sa.String(), nullable=False),
        sa.Column("budget", sa.Float(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "project_id", "package", name="uq_package_budget"),
    )
    op.create_index(
        "ix_package_budgets_organization_id", "package_budgets", ["organization_id"]
    )
    op.create_index("ix_package_budgets_project_id", "package_budgets", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_package_budgets_project_id", table_name="package_budgets")
    op.drop_index("ix_package_budgets_organization_id", table_name="package_budgets")
    op.drop_table("package_budgets")
