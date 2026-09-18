"""Invite delivery record + award notification record

Revision ID: 0024_email_delivery_records
Revises: 0023_computed_project_rows
Create Date: 2026-09-17

- organization_invites.emailed_at / email_error: whether (and when) the
  invitation email was actually delivered by a configured provider, and why
  the last attempt failed. GET /api/team used to report "emailed: true" for
  every invite whenever a provider existed, even when the send had failed.
- purchase_decisions.notifications: JSON record of the PO / decline emails
  sent (or not) for an award, so a failed notification is visible afterwards
  and can be re-sent via POST .../award/notify.
- purchase_decisions.status / superseded_by: a re-award (supersede=true)
  marks the earlier decision "superseded" so only one live PO is listed per
  package. Every pre-existing row is "active" (the default); a package with
  several rows keeps only its latest active — see the data step below.

batch_alter_table so this works on SQLite (local dev) as well as Postgres (prod).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024_email_delivery_records"
down_revision: Union[str, None] = "0023_computed_project_rows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("organization_invites") as batch_op:
        batch_op.add_column(sa.Column("emailed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("email_error", sa.String(), nullable=True))
    with op.batch_alter_table("purchase_decisions") as batch_op:
        batch_op.add_column(
            sa.Column("notifications", sa.Text(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("status", sa.String(), nullable=False, server_default="active")
        )
        batch_op.add_column(sa.Column("superseded_by", sa.String(), nullable=True))
    # Packages re-awarded before this revision: everything but the newest
    # decision per (org, project, package) is superseded by that newest one.
    op.execute(
        """
        UPDATE purchase_decisions
        SET status = 'superseded',
            superseded_by = (
                SELECT newer.id FROM purchase_decisions AS newer
                WHERE newer.organization_id = purchase_decisions.organization_id
                  AND newer.project_id = purchase_decisions.project_id
                  AND newer.package = purchase_decisions.package
                ORDER BY newer.created_at DESC, newer.id DESC LIMIT 1
            )
        WHERE EXISTS (
            SELECT 1 FROM purchase_decisions AS newer
            WHERE newer.organization_id = purchase_decisions.organization_id
              AND newer.project_id = purchase_decisions.project_id
              AND newer.package = purchase_decisions.package
              AND (newer.created_at > purchase_decisions.created_at
                   OR (newer.created_at = purchase_decisions.created_at
                       AND newer.id > purchase_decisions.id))
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("purchase_decisions") as batch_op:
        batch_op.drop_column("superseded_by")
        batch_op.drop_column("status")
        batch_op.drop_column("notifications")
    with op.batch_alter_table("organization_invites") as batch_op:
        batch_op.drop_column("email_error")
        batch_op.drop_column("emailed_at")
