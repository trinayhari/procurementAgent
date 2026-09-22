"""Thin httpx client for the Slack Web API, plus request signing.

Deliberately not slack_sdk: the app needs six methods and a file download.
Every call goes through `_http()`, which honours a module-level `transport`
hook so tests can mount an `httpx.MockTransport` (or monkeypatch the
functions outright). Tests must never reach slack.com.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger("procureai.slack")

API_BASE = "https://slack.com/api"
TIMEOUT_S = 15.0
# Reject requests whose timestamp is further than this from our clock.
SIGNATURE_MAX_AGE_S = 5 * 60

# Test hook: an httpx transport used for every request when set.
transport: Optional[httpx.BaseTransport] = None


class SlackError(Exception):
    """A Web API call answered ok=false (or transport failed). `error` is
    Slack's error string (e.g. not_in_channel) when there was one."""

    def __init__(self, error: str, method: str = ""):
        super().__init__(f"slack {method or 'call'} failed: {error}")
        self.error = error
        self.method = method


def _http() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_S, transport=transport, follow_redirects=True)


def _call(token: Optional[str], method: str, payload: Dict[str, Any], *, form: bool = False) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with _http() as http:
            if form:
                resp = http.post(f"{API_BASE}/{method}", data=payload, headers=headers)
            else:
                resp = http.post(f"{API_BASE}/{method}", json=payload, headers=headers)
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SlackError(str(exc) or exc.__class__.__name__, method) from exc
    if not data.get("ok"):
        raise SlackError(str(data.get("error") or "unknown_error"), method)
    return data


# ---------------------------------------------------------------- messages
def post_message(
    token: str, channel: str, blocks: List[dict], text: str, thread_ts: Optional[str] = None
) -> str:
    """chat.postMessage; returns the new message's ts."""
    payload: Dict[str, Any] = {"channel": channel, "text": text, "blocks": blocks, "unfurl_links": False}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return str(_call(token, "chat.postMessage", payload)["ts"])


def update_message(token: str, channel: str, ts: str, blocks: List[dict], text: str) -> str:
    """chat.update; replaces the blocks of an existing message."""
    payload = {"channel": channel, "ts": ts, "text": text, "blocks": blocks}
    return str(_call(token, "chat.update", payload)["ts"])


def post_ephemeral(
    token: str, channel: str, user: str, text: str, blocks: Optional[List[dict]] = None,
    thread_ts: Optional[str] = None,
) -> str:
    """chat.postEphemeral: visible only to `user`. Returns the message ts."""
    payload: Dict[str, Any] = {"channel": channel, "user": user, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return str(_call(token, "chat.postEphemeral", payload).get("message_ts", ""))


def respond(response_url: str, payload: Dict[str, Any]) -> None:
    """POST to an interaction's response_url (ephemeral by default)."""
    try:
        with _http() as http:
            http.post(response_url, json=payload)
    except httpx.HTTPError as exc:
        raise SlackError(str(exc) or exc.__class__.__name__, "response_url") from exc


# ------------------------------------------------------------------- lookups
def users_info(token: str, user_id: str) -> Dict[str, Any]:
    """users.info: the Slack user object (profile.email needs users:read.email)."""
    return _call(token, "users.info", {"user": user_id}, form=True)["user"]


def conversations_info(token: str, channel_id: str) -> Dict[str, Any]:
    """conversations.info: the channel object (name, is_private, ...)."""
    return _call(token, "conversations.info", {"channel": channel_id}, form=True)["channel"]


def download_file(token: str, url_private_download: str) -> bytes:
    """Fetch a shared file's bytes with the bot token (files:read)."""
    try:
        with _http() as http:
            resp = http.get(url_private_download, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SlackError(str(exc) or exc.__class__.__name__, "files.download") from exc
    # Slack answers an unauthenticated download with an HTML login page, not
    # a 401, so guard against storing that as a plan set.
    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("text/html"):
        raise SlackError("file_download_unauthorized", "files.download")
    return resp.content


# --------------------------------------------------------------------- oauth
def oauth_access(code: str) -> Dict[str, Any]:
    """oauth.v2.access: exchange the install code for the bot token. The
    redirect_uri is omitted on purpose: the app manifest configures exactly
    one, so Slack uses it and nothing here has to know the API's public URL."""
    return _call(
        None,
        "oauth.v2.access",
        {"code": code, "client_id": settings.slack_client_id, "client_secret": settings.slack_client_secret},
        form=True,
    )


def auth_revoke(token: str) -> None:
    """auth.revoke: invalidate a bot token on uninstall."""
    _call(token, "auth.revoke", {}, form=True)


# ------------------------------------------------------------------ signing
def verify_signature(
    secret: str, timestamp: str, body: bytes, signature: str, now: Optional[float] = None
) -> bool:
    """Check X-Slack-Signature over `v0:<timestamp>:<raw body>` with a
    constant-time compare, rejecting timestamps outside the replay window."""
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - ts) > SIGNATURE_MAX_AGE_S:
        return False
    if isinstance(body, str):
        body = body.encode("utf-8")
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """The signature Slack would send for `body` at `timestamp` (tests, scripts)."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    return "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
