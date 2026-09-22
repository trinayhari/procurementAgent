"""Slack settings endpoints (authed, scoped to the caller's organization).

Status, the install link, and channel-to-project links. The OAuth callback,
events, interactions and slash commands are public and live in
webhooks_slack.py.
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import projects as projects_repo
from app.repositories import slack as slack_repo
from app.schemas.slack import (
    SlackChannelLink,
    SlackChannelLinkRequest,
    SlackInstallUrl,
    SlackStatus,
)
from app.services.slack import client as slack_client
from app.services.slack import oauth as slack_oauth

logger = logging.getLogger("procureai.slack")

router = APIRouter(prefix="/api/slack", tags=["slack"])


def _links_payload(db: Session, org_id: str) -> List[dict]:
    names = {p["id"]: p["name"] for p in projects_repo.list_projects(db, org_id)}
    out = []
    for link in slack_repo.list_links(db, org_id):
        payload = link.to_dict()
        payload["projectName"] = names.get(link.project_id) if link.project_id else None
        out.append(payload)
    return out


@router.get("/status", response_model=SlackStatus)
def slack_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Server configuration + this org's installation and linked channels."""
    org_id = current_user.organization_id
    inst = slack_repo.installation_for_org(db, org_id)
    return {
        "configured": slack_oauth.configured(),
        "missing": slack_oauth.missing_settings(),
        "installed": inst is not None,
        "teamId": inst.team_id if inst else None,
        "teamName": inst.team_name if inst else None,
        "botUserId": inst.bot_user_id if inst else None,
        "installedAt": inst.created_at.isoformat() if inst and inst.created_at else None,
        "channels": _links_payload(db, org_id),
    }


@router.get("/install-url", response_model=SlackInstallUrl)
def install_url(current_user: User = Depends(get_current_user)):
    """The Slack consent URL, with a state bound to this org + user (10 min)."""
    if not slack_oauth.configured():
        raise HTTPException(status_code=409, detail="Slack is not configured on this server.")
    return {"url": slack_oauth.install_url(current_user.organization_id, current_user.id)}


@router.get("/channels", response_model=List[SlackChannelLink])
def list_channels(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _links_payload(db, current_user.organization_id)


@router.put("/channels/{channel_id}", response_model=SlackChannelLink)
def link_channel(
    channel_id: str,
    body: SlackChannelLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Link (or relink) a channel to one of the org's projects."""
    org_id = current_user.organization_id
    inst = slack_repo.installation_for_org(db, org_id)
    if inst is None:
        raise HTTPException(status_code=409, detail="Install the Slack app first.")
    project = projects_repo.get_project(db, org_id, body.projectId)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    link = slack_repo.set_link(
        db, org_id, team_id=inst.team_id, channel_id=channel_id,
        project_id=project["id"], channel_name=body.channelName,
    )
    audit_repo.log(
        db, org_id, current_user, "slack.channel_linked", "slack_channel_link", link.id,
        detail={"channelId": channel_id, "projectId": project["id"]},
    )
    payload = link.to_dict()
    payload["projectName"] = project["name"]
    return payload


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_channel(
    channel_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    org_id = current_user.organization_id
    if not slack_repo.delete_link(db, org_id, channel_id):
        raise HTTPException(status_code=404, detail="Channel link not found")
    audit_repo.log(
        db, org_id, current_user, "slack.channel_unlinked", "slack_channel_link", channel_id,
        detail={"channelId": channel_id},
    )
    return None


@router.delete("/installation", status_code=status.HTTP_204_NO_CONTENT)
def uninstall(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Disconnect the workspace: drop the token and every link, and revoke
    the token at Slack (best effort: a failed revoke still disconnects)."""
    org_id = current_user.organization_id
    inst = slack_repo.delete_installation(db, org_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Slack is not installed")
    try:
        slack_client.auth_revoke(inst.bot_token)
    except slack_client.SlackError as exc:
        logger.warning("slack auth.revoke failed for %s: %s", inst.team_id, exc)
    audit_repo.log(
        db, org_id, current_user, "slack.uninstalled", "slack_installation", inst.id,
        detail={"teamId": inst.team_id, "teamName": inst.team_name},
    )
    return None
