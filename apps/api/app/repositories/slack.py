"""Database accessors for the Slack integration.

Everything the settings UI and the notifier read is org-scoped. The one
deliberately unscoped lookup is `installation_for_team`: a Slack event or
button click arrives with a workspace `team_id` and no session, so the org
is derived FROM the installation (the same shape as invites-by-token).
"""
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.slack_channel_link import SlackChannelLink
from app.models.slack_installation import SlackInstallation


# ------------------------------------------------------------- installations
def installation_for_org(db: Session, org_id: str) -> Optional[SlackInstallation]:
    return db.scalar(
        select(SlackInstallation).where(SlackInstallation.organization_id == org_id)
    )


def installation_for_team(db: Session, team_id: str) -> Optional[SlackInstallation]:
    """Resolve the tenant an inbound Slack request belongs to. NOT org-scoped
    on purpose: the webhook has no org context until this returns."""
    if not team_id:
        return None
    return db.scalar(select(SlackInstallation).where(SlackInstallation.team_id == team_id))


def upsert_installation(
    db: Session,
    org_id: str,
    *,
    team_id: str,
    team_name: str,
    bot_user_id: str,
    bot_token: str,
    installed_by_user_id: str,
) -> SlackInstallation:
    """Record an OAuth install. A workspace re-installing (new token, maybe a
    new org) replaces its row; an org installing a second workspace replaces
    its previous one, since notices target one workspace per org."""
    row = installation_for_team(db, team_id)
    if row is None:
        row = installation_for_org(db, org_id)
    if row is None:
        row = SlackInstallation(id=uuid.uuid4().hex, organization_id=org_id, team_id=team_id, bot_token=bot_token,
                                installed_by_user_id=installed_by_user_id)
        db.add(row)
    row.organization_id = org_id
    row.team_id = team_id
    row.team_name = team_name or ""
    row.bot_user_id = bot_user_id or ""
    row.bot_token = bot_token
    row.installed_by_user_id = installed_by_user_id
    db.commit()
    db.refresh(row)
    return row


def delete_installation(db: Session, org_id: str) -> Optional[SlackInstallation]:
    """Uninstall: drop the token and every channel link. Returns the removed
    row (so the route can revoke the token) or None when nothing was installed."""
    row = installation_for_org(db, org_id)
    if row is None:
        return None
    for link in list_links(db, org_id):
        db.delete(link)
    db.delete(row)
    db.commit()
    return row


# ------------------------------------------------------------ channel links
def list_links(db: Session, org_id: str) -> List[SlackChannelLink]:
    return list(
        db.scalars(
            select(SlackChannelLink)
            .where(SlackChannelLink.organization_id == org_id)
            .order_by(SlackChannelLink.created_at, SlackChannelLink.channel_id)
        ).all()
    )


def link_for_channel(db: Session, org_id: str, team_id: str, channel_id: str) -> Optional[SlackChannelLink]:
    return db.scalar(
        select(SlackChannelLink).where(
            SlackChannelLink.organization_id == org_id,
            SlackChannelLink.team_id == team_id,
            SlackChannelLink.channel_id == channel_id,
        )
    )


def link_for_project(db: Session, org_id: str, project_id: str) -> Optional[SlackChannelLink]:
    """The channel a project's notices go to (the oldest link when several)."""
    return db.scalar(
        select(SlackChannelLink)
        .where(
            SlackChannelLink.organization_id == org_id,
            SlackChannelLink.project_id == project_id,
        )
        .order_by(SlackChannelLink.created_at)
    )


def set_link(
    db: Session,
    org_id: str,
    *,
    team_id: str,
    channel_id: str,
    project_id: Optional[str],
    channel_name: str = "",
) -> SlackChannelLink:
    """Link (or relink) a channel to a project. Creates the row when the
    channel is new; keeps the stored channel name when none is given."""
    row = link_for_channel(db, org_id, team_id, channel_id)
    if row is None:
        row = SlackChannelLink(
            id=uuid.uuid4().hex, organization_id=org_id, team_id=team_id, channel_id=channel_id
        )
        db.add(row)
    row.project_id = project_id
    if channel_name:
        row.channel_name = channel_name
    db.commit()
    db.refresh(row)
    return row


def delete_link(db: Session, org_id: str, channel_id: str) -> bool:
    """Unlink a channel. False when the org has no link for it (route 404s)."""
    rows = db.scalars(
        select(SlackChannelLink).where(
            SlackChannelLink.organization_id == org_id,
            SlackChannelLink.channel_id == channel_id,
        )
    ).all()
    if not rows:
        return False
    for row in rows:
        db.delete(row)
    db.commit()
    return True
