"""Slack public endpoints (no session): the OAuth callback, the Events API,
interactivity and slash commands. Mounted without auth in main.py.

Every Slack-originated request is verified against PROCUREAI_SLACK_SIGNING_SECRET
(HMAC-SHA256 over `v0:<timestamp>:<raw body>`, five-minute replay window).
With no secret configured, development accepts unsigned requests so a local
server can be driven with scripts/send_test_slack_event.py; production
refuses them. The callback is guarded by its signed `state` instead.

Slack expects a 2xx within three seconds, so events and button clicks are
acknowledged immediately and processed in a background task.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Optional
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.services.slack import client as slack_client
from app.services.slack import events as slack_events
from app.services.slack import interactions as slack_interactions
from app.services.slack import oauth as slack_oauth

logger = logging.getLogger("procureai.slack")

router = APIRouter(prefix="/api/webhooks/slack", tags=["webhooks"])


async def _verified_body(request: Request) -> bytes:
    """The raw body, after the signature check (401 when it fails)."""
    body = await request.body()
    secret = settings.slack_signing_secret
    if not secret:
        # Fail closed, exactly as the AgentMail webhook does: without the
        # secret a forged event is indistinguishable from a real one, so an
        # explicit opt-in is required and is itself refused in production.
        if settings.allow_unsigned_webhooks and settings.env != "production":
            return body
        raise HTTPException(status_code=401, detail="Slack signing secret is not configured")
    ok = slack_client.verify_signature(
        secret,
        request.headers.get("x-slack-request-timestamp", ""),
        body,
        request.headers.get("x-slack-signature", ""),
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid Slack signature")
    return body


def _form(body: bytes) -> Dict[str, str]:
    return {k: v[0] for k, v in parse_qs(body.decode("utf-8"), keep_blank_values=True).items()}


def _settings_redirect(**params: str) -> RedirectResponse:
    base = slack_oauth.app_base_url()
    query = urlencode(params)
    return RedirectResponse(f"{base}/#/settings?{query}" if base else f"/#/settings?{query}", status_code=302)


# ------------------------------------------------------------------- oauth
@router.get("/oauth/callback")
def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Where Slack sends the user after the consent screen. `state` proves
    which org and user started the install; the code is exchanged for the
    bot token and the browser lands back on Proq's settings page."""
    parsed = slack_oauth.parse_state(state or "")
    if parsed is None:
        raise HTTPException(status_code=400, detail="Invalid or expired install link. Start again from Settings.")
    org_id, user_id = parsed
    if error or not code:
        # The user cancelled on Slack's side (error=access_denied).
        return _settings_redirect(slack="error", reason=error or "cancelled")
    try:
        inst = slack_oauth.complete_install(db, org_id=org_id, user_id=user_id, code=code)
    except slack_client.SlackError as exc:
        logger.warning("slack oauth exchange failed for org %s: %s", org_id, exc)
        return _settings_redirect(slack="error", reason=exc.error)
    logger.info("slack installed for org %s: team %s (%s)", org_id, inst.team_id, inst.team_name)
    return _settings_redirect(slack="connected")


# ------------------------------------------------------------------ events
@router.post("/events")
async def events(request: Request, background: BackgroundTasks):
    # The url_verification handshake is answered BEFORE the signature check.
    # Slack sends it when you first save the Events request URL, which is
    # necessarily before the app exists and therefore before its signing
    # secret can be configured: checking the signature first makes the URL
    # impossible to verify on a deployment that refuses unsigned requests.
    # Echoing a challenge carries no data and performs no action, so there is
    # nothing for a forged one to gain. Everything else below is verified.
    raw = await request.body()
    try:
        envelope = json.loads(raw or b"{}")
    except ValueError:
        envelope = {}
    if envelope.get("type") == "url_verification":
        return PlainTextResponse(str(envelope.get("challenge") or ""))

    body = await _verified_body(request)
    try:
        envelope = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed event body")
    kind = envelope.get("type")
    if kind != "event_callback":
        return Response(status_code=200)
    event_id = str(envelope.get("event_id") or "")
    if not slack_events.mark_seen(event_id):
        # A retry of something already handled: acknowledge, do nothing.
        logger.info("slack event %s already seen (retry %s)", event_id, request.headers.get("x-slack-retry-num"))
        return Response(status_code=200)
    background.add_task(slack_events.process, envelope)
    return Response(status_code=200)


# ------------------------------------------------------------ interactions
@router.post("/interactions")
async def interactions(request: Request, background: BackgroundTasks):
    body = await _verified_body(request)
    raw = _form(body).get("payload", "")
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed interaction payload")
    if payload.get("type") == "block_actions":
        background.add_task(slack_interactions.process_interaction, payload)
    return Response(status_code=200)


# ---------------------------------------------------------------- commands
@router.post("/commands")
async def commands(request: Request, db: Session = Depends(get_db)):
    body = await _verified_body(request)
    form = _form(body)
    return JSONResponse(slack_interactions.handle_command(db, form))
