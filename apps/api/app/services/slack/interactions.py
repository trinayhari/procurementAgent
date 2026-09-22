"""Button clicks and slash commands.

Approve award: the card's button carries the approval url in `value`; the
token inside it is executed through services/approvals (owned by the
approvals work, imported lazily) as the clicking user's email, and the card
is rewritten into a confirmation with the PO numbers. Any failure goes back
to the clicker as an ephemeral message; the card is left alone so it can be
retried.

Slash commands answer inline (Slack shows the response to the invoker):
    /proq link <project name>   link this channel to the best-matching project
    /proq status                the project's latest activity
    /proq help
"""
from __future__ import annotations

import difflib
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.slack_installation import SlackInstallation
from app.repositories import events as events_repo
from app.repositories import projects as projects_repo
from app.repositories import slack as slack_repo
from app.services.slack import blocks as slack_blocks
from app.services.slack import client as slack_client
from app.services.slack import events as slack_events

logger = logging.getLogger("procureai.slack")

APPROVALS_NOT_WIRED_TEXT = "Approvals are not wired up yet: the award was not issued."

HELP_TEXT = (
    "*Proq* runs procurement from this channel.\n"
    "• Drop a plan set here with a line of context and I will build the BOM, "
    "source quotes and post the award card back in the thread.\n"
    "• `/proq link <project name>`: link this channel to a project\n"
    "• `/proq status`: the linked project's latest activity\n"
    "• `/proq help`: this message"
)


# ------------------------------------------------------------ approvals
def _execute_approval(db: Session, token: str, *, decided_by_email: str) -> Optional[dict]:
    """Call services.approvals.execute lazily; None when it is not merged yet."""
    try:
        from app.services import approvals

        execute = approvals.execute
    except (ImportError, AttributeError):
        logger.warning("slack approve: services.approvals.execute is not available")
        return None
    try:
        return execute(db, token, decided_by_email=decided_by_email)
    except NotImplementedError:
        logger.warning("slack approve: approvals.execute is still a stub")
        return None


def _po_numbers(result: dict) -> List[str]:
    for key in ("poNumbers", "po_numbers"):
        value = result.get(key)
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, dict):
            return [f"{k}: {v}" for k, v in value.items()]
    return []


def process_interaction(payload: dict) -> None:
    """Background entry point for one interactivity payload."""
    with SessionLocal() as db:
        try:
            handle_interaction(db, payload)
        except Exception:  # noqa: BLE001
            logger.exception("slack interaction failed")


def handle_interaction(db: Session, payload: dict) -> Optional[str]:
    if payload.get("type") != "block_actions":
        return "ignored:type"
    actions = [a for a in payload.get("actions") or [] if a.get("action_id") == slack_blocks.APPROVE_ACTION_ID]
    if not actions:
        return "ignored:no_approve"  # open_url buttons need nothing from us
    team_id = str((payload.get("team") or {}).get("id") or (payload.get("user") or {}).get("team_id") or "")
    installation = slack_repo.installation_for_team(db, team_id)
    if installation is None:
        return "ignored:no_installation"
    channel_id = str((payload.get("channel") or {}).get("id") or (payload.get("container") or {}).get("channel_id") or "")
    message_ts = str((payload.get("message") or {}).get("ts") or (payload.get("container") or {}).get("message_ts") or "")
    slack_user_id = str((payload.get("user") or {}).get("id") or "")
    token_value = str(actions[0].get("value") or "")
    approval_token = slack_blocks.approval_token_from(token_value)

    def tell(text: str) -> None:
        try:
            slack_client.post_ephemeral(installation.bot_token, channel_id, slack_user_id, text)
        except slack_client.SlackError as exc:
            logger.warning("slack ephemeral failed: %s", exc)

    if not approval_token:
        tell("That button does not carry an approval link any more. Open the award in Proq instead.")
        return "error:no_token"
    user = slack_events.resolve_user(db, installation, slack_user_id)
    if user is None:
        email = slack_events.slack_user_email(installation, slack_user_id) or "your work email"
        tell(slack_events.UNKNOWN_USER_TEXT.format(email=email, base=slack_events._app_base()))
        return "unknown_user"
    try:
        result = _execute_approval(db, approval_token, decided_by_email=user.email)
    except Exception as exc:  # noqa: BLE001 - surface the reason to the clicker
        detail = getattr(exc, "detail", None) or str(exc) or exc.__class__.__name__
        tell(f"I could not issue the award: {detail}")
        return "error:approval"
    if result is None:
        tell(APPROVALS_NOT_WIRED_TEXT)
        return "approvals_unavailable"
    pos = _po_numbers(result)
    lines = [f"Approved by {user.name or user.email}"]
    if pos:
        lines.append("POs issued: " + ", ".join(pos))
    else:
        lines.append("POs issued")
    title = str(result.get("title") or "Award approved")
    if channel_id and message_ts:
        slack_client.update_message(
            installation.bot_token, channel_id, message_ts,
            slack_blocks.render_confirmation(title, lines), title,
        )
    return "approved"


# --------------------------------------------------------------- commands
def _best_project(projects: List[dict], query: str) -> Optional[dict]:
    q = query.strip().lower()
    if not q or not projects:
        return None
    for p in projects:
        if p["name"].strip().lower() == q or p["id"] == q:
            return p
    contains = [p for p in projects if q in p["name"].lower()]
    if len(contains) == 1:
        return contains[0]
    names = {p["name"].lower(): p for p in projects}
    match = difflib.get_close_matches(q, list(names), n=1, cutoff=0.6)
    return names[match[0]] if match else (contains[0] if contains else None)


def _ephemeral(text: str) -> Dict[str, Any]:
    return {"response_type": "ephemeral", "text": text}


def handle_command(db: Session, form: Dict[str, str]) -> Dict[str, Any]:
    """Answer a slash command; the dict is the HTTP response body."""
    text = (form.get("text") or "").strip()
    verb, _, rest = text.partition(" ")
    verb = verb.lower()
    if verb in ("", "help"):
        return _ephemeral(HELP_TEXT)
    installation = slack_repo.installation_for_team(db, form.get("team_id") or "")
    if installation is None:
        return _ephemeral("This workspace is not connected to Proq yet. Install the app from Proq's settings.")
    org_id = installation.organization_id
    channel_id = form.get("channel_id") or ""
    channel_name = form.get("channel_name") or ""
    if verb == "link":
        if not rest.strip():
            return _ephemeral("Usage: `/proq link <project name>`")
        projects = projects_repo.list_projects(db, org_id)
        project = _best_project(projects, rest)
        if project is None:
            return _ephemeral(f"I could not find a project matching \"{rest.strip()}\".")
        slack_repo.set_link(
            db, org_id, team_id=installation.team_id, channel_id=channel_id,
            project_id=project["id"], channel_name=channel_name,
        )
        return _ephemeral(f"Linked #{channel_name or channel_id} to *{project['name']}*.")
    if verb == "status":
        link = slack_repo.link_for_channel(db, org_id, installation.team_id, channel_id)
        if link is None or not link.project_id:
            return _ephemeral("This channel is not linked to a project yet. Try `/proq link <project name>`.")
        project = projects_repo.get_project(db, org_id, link.project_id)
        if project is None:
            return _ephemeral("The linked project no longer exists. Try `/proq link <project name>`.")
        events = events_repo.list_for_project(db, org_id, link.project_id, limit=5)
        if not events:
            return _ephemeral(f"*{project['name']}*: no activity yet.")
        lines = [f"• {e['title']}" + (f" ({e['meta']})" if e.get("meta") else "") + f", {e['time']}" for e in events]
        return _ephemeral(f"*{project['name']}*, latest activity:\n" + "\n".join(lines))
    return _ephemeral(HELP_TEXT)
