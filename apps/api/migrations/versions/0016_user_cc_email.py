"""rename users.sender_email → users.cc_email

Revision ID: 0016_user_cc_email
Revises: 0015_document_checksum
Create Date: 2026-07-28

Outbound mail is now always sent from the workspace mailbox
(PROCUREAI_GMAIL_SENDER_ADDRESS); the address a user configured is Cc'd instead
of used as `From:`. A rename (not a drop + add) keeps every existing value: the
address someone entered as their From is exactly the one they want copied.

batch_alter_table so this works on SQLite (local dev) as well as Postgres (prod).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_user_cc_email"
down_revision: Union[str, None] = "0015_document_checksum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("sender_email", new_column_name="cc_email")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("cc_email", new_column_name="sender_email")
