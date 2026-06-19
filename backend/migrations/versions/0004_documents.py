"""add documents table for persisted uploads + extracted BOMs

Revision ID: 0004_documents
Revises: 0003_quotes
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_documents"
down_revision: Union[str, None] = "0003_quotes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("status_tone", sa.String(), nullable=False),
        sa.Column("items", sa.String(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("processing", sa.Boolean(), nullable=False),
        sa.Column("has_file", sa.Boolean(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=True),
        sa.Column("plan_type", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("mocked", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
        sa.Column("reviewed_at", sa.String(), nullable=True),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("line_items", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index("ix_documents_project_id", "documents", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_project_id", table_name="documents")
    op.drop_table("documents")
