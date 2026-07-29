"""organization_invites table (team invite flow)

A pending invitation for a teammate to join an existing organization. Accepting
one (public accept endpoint, resolved by token) creates a user in the inviting
org — the invite flow the multi-tenancy work left as a TODO.

Revision ID: 0017_organization_invites
Revises: 0016_organizations
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017_organization_invites"
down_revision: Union[str, None] = "0016_organizations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_invites",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("invited_by_user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
        sa.UniqueConstraint("token"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
    )
    op.create_index(
        "ix_organization_invites_organization_id", "organization_invites", ["organization_id"]
    )
    op.create_index("ix_organization_invites_email", "organization_invites", ["email"])
    op.create_index("ix_organization_invites_token", "organization_invites", ["token"])


def downgrade() -> None:
    op.drop_index("ix_organization_invites_token", table_name="organization_invites")
    op.drop_index("ix_organization_invites_email", table_name="organization_invites")
    op.drop_index("ix_organization_invites_organization_id", table_name="organization_invites")
    op.drop_table("organization_invites")
