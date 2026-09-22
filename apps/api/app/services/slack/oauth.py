"""The install handshake: a signed `state` bound to the org + user who
clicked Install, and the code exchange that records the installation.

`state` is a short-lived scoped JWT (HMAC-SHA256 with settings.jwt_secret),
so the public callback can trust which org the workspace belongs to without
a session: whoever finishes the Slack consent screen can only attach the
workspace to the org that minted the link, and only for ten minutes.
"""
from __future__ import annotations

from typing import Optional, Tuple
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import create_scoped_token, verify_scoped_token
from app.repositories import slack as slack_repo
from app.services.slack import client as slack_client

AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
STATE_SCOPE = "slack-install"
STATE_TTL_MINUTES = 10

# Bot scopes the app needs. Keep docs/slack-setup.md's manifest in sync.
BOT_SCOPES = [
    "chat:write",
    "channels:history",
    "groups:history",
    "channels:read",
    "groups:read",
    "files:read",
    "app_mentions:read",
    "commands",
    "users:read",
    "users:read.email",
]


def configured() -> bool:
    return bool(settings.slack_client_id and settings.slack_client_secret and settings.slack_signing_secret)


def missing_settings() -> list:
    return [
        name
        for name, value in (
            ("PROCUREAI_SLACK_CLIENT_ID", settings.slack_client_id),
            ("PROCUREAI_SLACK_CLIENT_SECRET", settings.slack_client_secret),
            ("PROCUREAI_SLACK_SIGNING_SECRET", settings.slack_signing_secret),
        )
        if not value
    ]


def make_state(org_id: str, user_id: str) -> str:
    return create_scoped_token(f"{org_id}:{user_id}", STATE_SCOPE, STATE_TTL_MINUTES)


def parse_state(state: str) -> Optional[Tuple[str, str]]:
    """(org_id, user_id) for a valid, unexpired state; None otherwise."""
    subject = verify_scoped_token(state or "", STATE_SCOPE)
    if not subject or ":" not in subject:
        return None
    org_id, _, user_id = subject.partition(":")
    return (org_id, user_id) if org_id and user_id else None


def install_url(org_id: str, user_id: str) -> str:
    params = {
        "client_id": settings.slack_client_id,
        "scope": ",".join(BOT_SCOPES),
        "state": make_state(org_id, user_id),
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def app_base_url() -> str:
    base = settings.app_base_url or (settings.cors_origins[0] if settings.cors_origins else "")
    return base.rstrip("/")


def complete_install(db: Session, *, org_id: str, user_id: str, code: str):
    """Exchange the code and upsert the installation. Raises SlackError when
    Slack refuses the code."""
    data = slack_client.oauth_access(code)
    team = data.get("team") or {}
    return slack_repo.upsert_installation(
        db,
        org_id,
        team_id=str(team.get("id") or ""),
        team_name=str(team.get("name") or ""),
        bot_user_id=str(data.get("bot_user_id") or ""),
        bot_token=str(data.get("access_token") or ""),
        installed_by_user_id=user_id,
    )
