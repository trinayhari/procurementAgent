"""Events API handling: a plan set posted in a linked channel, or a mention.

The route acknowledges within Slack's 3-second window and schedules
`process(envelope)` as a background task; this module opens its own DB
session because the request's session is gone by then.

What counts as a request for the agent:
  * a `message` carrying files in a channel that has a SlackChannelLink
    (the customer's project channel), or
  * an `app_mention` anywhere the bot is (a question, a note, or a plan set
    shared with "@Proq here's the site set").
A message that mentions the bot arrives as BOTH events; the `message` copy
is skipped so it is handled once, via `app_mention`.

Identity: the Slack user's email (users.info) must match a Proq User in the
installation's org. Otherwise the agent says so, ephemerally, and stops.
Files are downloaded with the bot token, stored through services/storage,
and handed to intake with a ThreadRef pointing at the message so every
later notice lands in that thread. When the channel had no project yet the
intake's project becomes the link.

Dedupe: Slack retries an event it did not see a 2xx for within 3 seconds.
Seen event_ids are kept in memory with a one-hour TTL (per process; a
retry landing on another worker is processed again, which is acceptable
while the API runs a single worker). No table, so nothing to migrate.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import threading
import time
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models.slack_installation import SlackInstallation
from app.models.user import User
from app.repositories import slack as slack_repo
from app.repositories import users as users_repo
from app.services import storage
from app.services.notify import ThreadRef
from app.services.slack import blocks as slack_blocks
from app.services.slack import client as slack_client
from app.services.slack import intake_bridge

logger = logging.getLogger("procureai.slack")

SEEN_TTL_S = 60 * 60
_seen: Dict[str, float] = {}
_seen_lock = threading.Lock()

_MENTION_RE = re.compile(r"<@[A-Z0-9]+(\|[^>]*)?>")
# Message subtypes that are edits/deletes/joins, never a request.
_IGNORED_SUBTYPES = {
    "bot_message", "message_changed", "message_deleted", "channel_join", "channel_leave",
    "channel_topic", "channel_purpose", "thread_broadcast", "message_replied",
}

UNKNOWN_USER_TEXT = (
    "I don't know who you are in Proq yet: sign in with {email} at {base} "
    "(or ask a teammate to invite that address) and post again."
)


# ---------------------------------------------------------------- dedupe
def mark_seen(event_id: str, now: Optional[float] = None) -> bool:
    """Record an event id. Returns False when it was already seen (a retry)."""
    if not event_id:
        return True
    now = now if now is not None else time.monotonic()
    with _seen_lock:
        for key, ts in list(_seen.items()):
            if now - ts > SEEN_TTL_S:
                del _seen[key]
        if event_id in _seen:
            return False
        _seen[event_id] = now
        return True


def reset_seen() -> None:
    """Tests only."""
    with _seen_lock:
        _seen.clear()


# ------------------------------------------------------------------ helpers
def strip_mentions(text: str) -> str:
    return _MENTION_RE.sub("", text or "").strip()


def store_bytes(data: bytes, filename: str) -> storage.StoredFile:
    """Write downloaded bytes through the storage backend (same path an
    upload takes: temp file, then persist under a unique name)."""
    safe_name = os.path.basename(filename or "file") or "file"
    suffix = os.path.splitext(safe_name)[1].lower()
    fd, tmp_path = tempfile.mkstemp(prefix="procureai-slack-", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    temp = storage.StoredFile(locator=tmp_path, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    return storage.persist_temp(temp, safe_name)


def resolve_user(db: Session, installation: SlackInstallation, slack_user_id: str) -> Optional[User]:
    """The Proq user behind a Slack user id, in the installation's org."""
    try:
        info = slack_client.users_info(installation.bot_token, slack_user_id)
    except slack_client.SlackError as exc:
        logger.warning("slack users.info failed for %s: %s", slack_user_id, exc)
        return None
    email = str((info.get("profile") or {}).get("email") or "").strip().lower()
    if not email:
        return None
    user = users_repo.get_by_email(db, email)
    if user is None or user.organization_id != installation.organization_id:
        return None
    return user


def slack_user_email(installation: SlackInstallation, slack_user_id: str) -> str:
    try:
        info = slack_client.users_info(installation.bot_token, slack_user_id)
    except slack_client.SlackError:
        return ""
    return str((info.get("profile") or {}).get("email") or "").strip().lower()


def channel_name(installation: SlackInstallation, channel_id: str) -> str:
    try:
        return str(slack_client.conversations_info(installation.bot_token, channel_id).get("name") or "")
    except slack_client.SlackError:
        return ""


def _app_base() -> str:
    base = settings.app_base_url or (settings.cors_origins[0] if settings.cors_origins else "")
    return base.rstrip("/") or "Proq"


def download_attachments(installation: SlackInstallation, files: List[dict]) -> List[dict]:
    """Fetch every shared file and store it; returns intake attachment dicts."""
    out: List[dict] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024
    for f in files or []:
        url = f.get("url_private_download") or f.get("url_private")
        name = f.get("name") or f.get("title") or "file"
        if not url:
            continue
        if int(f.get("size") or 0) > max_bytes:
            logger.warning("slack file %s skipped: %s bytes over the cap", name, f.get("size"))
            continue
        try:
            data = slack_client.download_file(installation.bot_token, url)
        except slack_client.SlackError as exc:
            logger.warning("slack file %s download failed: %s", name, exc)
            continue
        stored = store_bytes(data, name)
        out.append(
            {
                "filename": name,
                "mimeType": f.get("mimetype") or "application/octet-stream",
                "size": stored.size,
                "locator": stored.locator,
            }
        )
    return out


# ------------------------------------------------------------------- entry
def process(envelope: dict) -> None:
    """Background entry point for one event_callback envelope."""
    with SessionLocal() as db:
        try:
            handle_event(db, envelope)
        except Exception:  # noqa: BLE001 - a failed event must not crash the worker
            logger.exception("slack event failed: %s", envelope.get("event_id"))


def handle_event(db: Session, envelope: dict) -> Optional[str]:
    """Route one envelope. Returns a short outcome string (for logs/tests)."""
    event = envelope.get("event") or {}
    etype = event.get("type")
    if etype not in ("message", "app_mention"):
        return "ignored:type"
    if event.get("bot_id") or event.get("subtype") in _IGNORED_SUBTYPES:
        return "ignored:bot"
    installation = slack_repo.installation_for_team(db, str(envelope.get("team_id") or ""))
    if installation is None:
        return "ignored:no_installation"
    if etype == "message":
        if installation.bot_user_id and f"<@{installation.bot_user_id}>" in (event.get("text") or ""):
            return "ignored:mention_dup"  # handled by the app_mention copy
        if not event.get("files"):
            return "ignored:no_files"
    channel_id = str(event.get("channel") or "")
    org_id = installation.organization_id
    link = slack_repo.link_for_channel(db, org_id, installation.team_id, channel_id)
    if etype == "message" and link is None:
        return "ignored:unlinked"

    slack_user_id = str(event.get("user") or "")
    thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
    user = resolve_user(db, installation, slack_user_id)
    if user is None:
        email = slack_user_email(installation, slack_user_id) or "your work email"
        slack_client.post_ephemeral(
            installation.bot_token, channel_id, slack_user_id,
            UNKNOWN_USER_TEXT.format(email=email, base=_app_base()), thread_ts=thread_ts,
        )
        return "unknown_user"

    name = (link.channel_name if link and link.channel_name else "") or channel_name(installation, channel_id)
    attachments = download_attachments(installation, event.get("files") or [])
    thread = ThreadRef(channel="slack", slack_channel_id=channel_id, slack_thread_ts=thread_ts)
    result = intake_bridge.handle(
        db,
        org_id=org_id,
        user=user,
        text=strip_mentions(event.get("text") or ""),
        subject=name,
        attachments=attachments,
        thread=thread,
    )
    if result is None:
        slack_client.post_message(
            installation.bot_token, channel_id, slack_blocks.render_text(intake_bridge.NOT_WIRED_TEXT),
            intake_bridge.NOT_WIRED_TEXT, thread_ts=thread_ts
        )
        return "intake_unavailable"
    project_id = getattr(result, "project_id", None)
    if project_id and (link is None or not link.project_id):
        slack_repo.set_link(
            db, org_id, team_id=installation.team_id, channel_id=channel_id,
            project_id=project_id, channel_name=name,
        )
        return "handled:linked"
    return "handled"
