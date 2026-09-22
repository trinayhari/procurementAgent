"""Proq as a coworker: agent inboxes, inbound mail, approvals, POs, Slack

Revision ID: 0025_agent_coworker
Revises: 0024_email_delivery_records
Create Date: 2026-09-21

- organizations.agentmail_inbox_id / po_counter: the org's AgentMail agent
  inbox (created lazily) and the per-org purchase-order counter.
- inbound_emails: every email an agent inbox receives, stored before
  processing (quote ingest and intake consume it).
- approval_tokens / package_recommendations: signed single-use award
  approval links and the recommendation they were minted for.
- purchase_decisions.po_numbers: one PO number per winning supplier.
- projects.need_by / rfqs.need_by: the material need-by date (ISO
  YYYY-MM-DD); RFQs inherit the project's at draft time.
- slack_installations / slack_channel_links: the org's Slack app install
  and channel-to-project links.

batch_alter_table so this works on SQLite (local dev) as well as Postgres.
Pre-existing schema drift autogenerate also reported (organization_id foreign
keys on older tables, invite token index uniqueness) is deliberately left out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0025_agent_coworker'
down_revision: Union[str, None] = '0024_email_delivery_records'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('approval_tokens',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('organization_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('package', sa.String(), nullable=False),
    sa.Column('package_label', sa.String(), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('token', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('decided_by_email', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('approval_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_tokens_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_tokens_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_tokens_token'), ['token'], unique=True)

    op.create_table('inbound_emails',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('organization_id', sa.String(), nullable=True),
    sa.Column('provider_message_id', sa.String(), nullable=False),
    sa.Column('inbox_id', sa.String(), nullable=False),
    sa.Column('thread_id', sa.String(), nullable=False),
    sa.Column('rfc_message_id', sa.String(), nullable=False),
    sa.Column('in_reply_to', sa.String(), nullable=False),
    sa.Column('references', sa.Text(), nullable=False),
    sa.Column('from_email', sa.String(), nullable=False),
    sa.Column('from_name', sa.String(), nullable=False),
    sa.Column('to_addresses', sa.Text(), nullable=False),
    sa.Column('cc_addresses', sa.Text(), nullable=False),
    sa.Column('subject', sa.String(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('html', sa.Text(), nullable=False),
    sa.Column('attachments', sa.Text(), nullable=False),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('rfq_id', sa.String(), nullable=True),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('processed_at', sa.DateTime(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('inbound_emails', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_inbound_emails_from_email'), ['from_email'], unique=False)
        batch_op.create_index(batch_op.f('ix_inbound_emails_in_reply_to'), ['in_reply_to'], unique=False)
        batch_op.create_index(batch_op.f('ix_inbound_emails_inbox_id'), ['inbox_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_inbound_emails_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_inbound_emails_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_inbound_emails_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_inbound_emails_provider_message_id'), ['provider_message_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_inbound_emails_rfc_message_id'), ['rfc_message_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_inbound_emails_rfq_id'), ['rfq_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_inbound_emails_thread_id'), ['thread_id'], unique=False)

    op.create_table('package_recommendations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('organization_id', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=False),
    sa.Column('package', sa.String(), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('token_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('superseded_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('package_recommendations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_package_recommendations_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_package_recommendations_project_id'), ['project_id'], unique=False)

    op.create_table('slack_channel_links',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('organization_id', sa.String(), nullable=False),
    sa.Column('team_id', sa.String(), nullable=False),
    sa.Column('channel_id', sa.String(), nullable=False),
    sa.Column('channel_name', sa.String(), nullable=False),
    sa.Column('project_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('team_id', 'channel_id', name='uq_slack_channel_links_team_channel')
    )
    with op.batch_alter_table('slack_channel_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_slack_channel_links_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_slack_channel_links_project_id'), ['project_id'], unique=False)

    op.create_table('slack_installations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('organization_id', sa.String(), nullable=False),
    sa.Column('team_id', sa.String(), nullable=False),
    sa.Column('team_name', sa.String(), nullable=False),
    sa.Column('bot_user_id', sa.String(), nullable=False),
    sa.Column('bot_token', sa.String(), nullable=False),
    sa.Column('installed_by_user_id', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('slack_installations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_slack_installations_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_slack_installations_team_id'), ['team_id'], unique=True)

    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('agentmail_inbox_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('po_counter', sa.Integer(), server_default='0', nullable=False))
        batch_op.create_unique_constraint('uq_organizations_agentmail_inbox_id', ['agentmail_inbox_id'])

    with op.batch_alter_table('purchase_decisions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('po_numbers', sa.Text(), nullable=False, server_default='[]'))

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('need_by', sa.String(), nullable=True))

    with op.batch_alter_table('rfqs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('need_by', sa.String(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('rfqs', schema=None) as batch_op:
        batch_op.drop_column('need_by')

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('need_by')

    with op.batch_alter_table('purchase_decisions', schema=None) as batch_op:
        batch_op.drop_column('po_numbers')

    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_organizations_agentmail_inbox_id', type_='unique')
        batch_op.drop_column('po_counter')
        batch_op.drop_column('agentmail_inbox_id')

    with op.batch_alter_table('slack_installations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_slack_installations_team_id'))
        batch_op.drop_index(batch_op.f('ix_slack_installations_organization_id'))

    op.drop_table('slack_installations')
    with op.batch_alter_table('slack_channel_links', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_slack_channel_links_project_id'))
        batch_op.drop_index(batch_op.f('ix_slack_channel_links_organization_id'))

    op.drop_table('slack_channel_links')
    with op.batch_alter_table('package_recommendations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_package_recommendations_project_id'))
        batch_op.drop_index(batch_op.f('ix_package_recommendations_organization_id'))

    op.drop_table('package_recommendations')
    with op.batch_alter_table('inbound_emails', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_inbound_emails_thread_id'))
        batch_op.drop_index(batch_op.f('ix_inbound_emails_rfq_id'))
        batch_op.drop_index(batch_op.f('ix_inbound_emails_rfc_message_id'))
        batch_op.drop_index(batch_op.f('ix_inbound_emails_provider_message_id'))
        batch_op.drop_index(batch_op.f('ix_inbound_emails_project_id'))
        batch_op.drop_index(batch_op.f('ix_inbound_emails_organization_id'))
        batch_op.drop_index(batch_op.f('ix_inbound_emails_kind'))
        batch_op.drop_index(batch_op.f('ix_inbound_emails_inbox_id'))
        batch_op.drop_index(batch_op.f('ix_inbound_emails_in_reply_to'))
        batch_op.drop_index(batch_op.f('ix_inbound_emails_from_email'))

    op.drop_table('inbound_emails')
    with op.batch_alter_table('approval_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approval_tokens_token'))
        batch_op.drop_index(batch_op.f('ix_approval_tokens_project_id'))
        batch_op.drop_index(batch_op.f('ix_approval_tokens_organization_id'))

    op.drop_table('approval_tokens')
