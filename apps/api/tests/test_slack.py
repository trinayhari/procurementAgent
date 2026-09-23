"""Slack integration: request signing, the Events API path from a message
with a file to the intake bridge, button clicks into approvals, the OAuth
callback, the SlackNotifier's Block Kit rendering, and org scoping of the
settings endpoints.

Nothing here reaches slack.com: every client function the handlers call is
monkeypatched, and the signature tests sign with a test secret. Intake and
approvals are owned by other workstreams and are stubbed the way the bridge
expects them (`services.inbound.intake.handle_request`,
`services.approvals.execute`).
"""
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from app.config import settings
from app.db import SessionLocal
from app.repositories import slack as slack_repo
from app.services import notify
from app.services.notify import slack as notify_slack
from app.services.slack import blocks as slack_blocks
from app.services.slack import client as slack_client
from app.services.slack import events as slack_events
from app.services.slack import interactions as slack_interactions
from app.services.slack import oauth as slack_oauth

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"
TEAM = "T0AAA"
CHANNEL = "C0RIVER"
BOT_TOKEN = "xoxb-test-token"
BOT_USER = "U0BOT"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _register(client, email, company):
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "name": email.split("@")[0], "company": company},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}, r.json()["user"]


def _new_project(client, headers, name):
    r = client.post("/api/projects", headers=headers, json={"name": name, "loc": "Austin, TX", "type": "Commercial"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _install(org_id, user_id, team_id=TEAM):
    with SessionLocal() as db:
        return slack_repo.upsert_installation(
            db, org_id, team_id=team_id, team_name="Alpha GC", bot_user_id=BOT_USER,
            bot_token=BOT_TOKEN, installed_by_user_id=user_id,
        ).id


def _link(org_id, channel_id, project_id, team_id=TEAM, name="riverside-wtp"):
    with SessionLocal() as db:
        slack_repo.set_link(db, org_id, team_id=team_id, channel_id=channel_id, project_id=project_id, channel_name=name)


def _signed_headers(body, ts=None, secret=SECRET):
    ts = str(int(ts if ts is not None else time.time()))
    return {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": slack_client.sign(secret, ts, body),
        "Content-Type": "application/json",
    }


def _message_event(user="U0PM", text="Riverside WTP site set, need it by Oct 15", files=None, event_id="Ev1", channel=CHANNEL, ts="1700000000.000100"):
    return {
        "type": "event_callback",
        "team_id": TEAM,
        "event_id": event_id,
        "event": {
            "type": "message",
            "subtype": "file_share" if files else None,
            "channel": channel,
            "user": user,
            "text": text,
            "ts": ts,
            "files": files or [],
        },
    }


PLAN_FILE = {
    "id": "F1", "name": "C-101 site plan.pdf", "mimetype": "application/pdf", "size": 12,
    "url_private_download": "https://files.slack.com/files-pri/T0AAA-F1/download/c-101.pdf",
}


@pytest.fixture()
def slack_fakes(monkeypatch):
    """Monkeypatch every outbound Slack call and record what was sent."""
    calls = SimpleNamespace(messages=[], ephemerals=[], updates=[], downloads=[], emails={})
    calls.emails = {"U0PM": "pm@alpha-gc.com", "U0STRANGER": "stranger@else.com"}

    def users_info(token, user_id):
        assert token == BOT_TOKEN
        return {"id": user_id, "profile": {"email": calls.emails.get(user_id, "")}}

    def download_file(token, url):
        assert token == BOT_TOKEN
        calls.downloads.append(url)
        return b"%PDF-1.4 fake"

    def post_message(token, channel, blocks, text, thread_ts=None):
        calls.messages.append({"channel": channel, "blocks": blocks, "text": text, "thread_ts": thread_ts})
        return "1700000000.000200"

    def post_ephemeral(token, channel, user, text, blocks=None, thread_ts=None):
        calls.ephemerals.append({"channel": channel, "user": user, "text": text})
        return ""

    def update_message(token, channel, ts, blocks, text):
        calls.updates.append({"channel": channel, "ts": ts, "blocks": blocks, "text": text})
        return ts

    monkeypatch.setattr(slack_client, "users_info", users_info)
    monkeypatch.setattr(slack_client, "download_file", download_file)
    monkeypatch.setattr(slack_client, "post_message", post_message)
    monkeypatch.setattr(slack_client, "post_ephemeral", post_ephemeral)
    monkeypatch.setattr(slack_client, "update_message", update_message)
    monkeypatch.setattr(slack_client, "conversations_info", lambda token, channel: {"id": channel, "name": "riverside-wtp"})
    slack_events.reset_seen()
    return calls


@pytest.fixture()
def intake_stub(monkeypatch):
    """A fake services.inbound.intake.handle_request that records its call."""
    from app.services.inbound import intake

    seen = []

    def handle_request(db, *, org_id, user, text, subject, attachments, thread, project_id=None):
        seen.append({"org_id": org_id, "user": user.email, "text": text, "subject": subject,
                     "attachments": attachments, "thread": thread, "project_id": project_id})
        return SimpleNamespace(project_id=getattr(handle_request, "project_id", "riverside-wtp"))

    monkeypatch.setattr(intake, "handle_request", handle_request, raising=False)
    return seen, handle_request


@pytest.fixture()
def signed(monkeypatch):
    monkeypatch.setattr(settings, "slack_signing_secret", SECRET)


# --------------------------------------------------------------------------- #
# signing
# --------------------------------------------------------------------------- #

def test_verify_signature_accepts_valid_and_rejects_bad_or_stale():
    body = b'{"type":"url_verification","challenge":"abc"}'
    now = 1_700_000_000
    ts = str(now)
    sig = slack_client.sign(SECRET, ts, body)
    assert slack_client.verify_signature(SECRET, ts, body, sig, now=now)
    assert not slack_client.verify_signature(SECRET, ts, body + b" ", sig, now=now)
    assert not slack_client.verify_signature(SECRET, ts, body, "v0=" + "0" * 64, now=now)
    assert not slack_client.verify_signature("other-secret", ts, body, sig, now=now)
    # Six minutes old: outside the replay window even with a correct HMAC.
    assert not slack_client.verify_signature(SECRET, ts, body, sig, now=now + 6 * 60)
    assert not slack_client.verify_signature(SECRET, "not-a-number", body, sig, now=now)
    assert not slack_client.verify_signature("", ts, body, sig, now=now)


def test_events_rejects_unsigned_when_secret_set(client, signed):
    # A real event, not the url_verification handshake: that one is answered
    # before the signature check on purpose (see the handshake test below).
    body = json.dumps({"type": "event_callback", "event_id": "Ev1", "event": {}}).encode()
    r = client.post("/api/webhooks/slack/events", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 401
    r = client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body, secret="wrong"))
    assert r.status_code == 401
    r = client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body, ts=time.time() - 600))
    assert r.status_code == 401


def test_events_refuses_unsigned_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    body = json.dumps({"type": "event_callback", "event_id": "Ev2", "event": {}}).encode()
    r = client.post("/api/webhooks/slack/events", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 401


def test_url_verification_echoes_challenge(client, signed):
    body = json.dumps({"type": "url_verification", "challenge": "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P"}).encode()
    r = client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert r.status_code == 200
    assert r.text == "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P"


# --------------------------------------------------------------------------- #
# events: message with a file
# --------------------------------------------------------------------------- #

def test_message_with_file_in_linked_channel_reaches_intake(client, signed, slack_fakes, intake_stub):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)
    seen, _ = intake_stub

    body = json.dumps(_message_event(files=[PLAN_FILE])).encode()
    r = client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert r.status_code == 200  # background task runs before TestClient returns

    assert slack_fakes.downloads == [PLAN_FILE["url_private_download"]]
    assert len(seen) == 1
    call = seen[0]
    assert call["org_id"] == me["organizationId"]
    assert call["user"] == "pm@alpha-gc.com"
    assert call["text"] == "Riverside WTP site set, need it by Oct 15"
    assert call["subject"] == "riverside-wtp"
    assert call["thread"] == notify.ThreadRef(channel="slack", slack_channel_id=CHANNEL, slack_thread_ts="1700000000.000100")
    [att] = call["attachments"]
    assert att["filename"] == "C-101 site plan.pdf"
    assert att["mimeType"] == "application/pdf"
    assert att["size"] == len(b"%PDF-1.4 fake")
    with open(att["locator"], "rb") as fh:
        assert fh.read() == b"%PDF-1.4 fake"
    assert slack_fakes.ephemerals == []


def test_retry_of_seen_event_is_not_reprocessed(client, signed, slack_fakes, intake_stub):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)
    seen, _ = intake_stub

    body = json.dumps(_message_event(files=[PLAN_FILE], event_id="Ev42")).encode()
    r = client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert r.status_code == 200
    retry = dict(_signed_headers(body), **{"X-Slack-Retry-Num": "1", "X-Slack-Retry-Reason": "http_timeout"})
    r = client.post("/api/webhooks/slack/events", content=body, headers=retry)
    assert r.status_code == 200
    assert len(seen) == 1
    assert len(slack_fakes.downloads) == 1


def test_unknown_slack_user_gets_ephemeral_and_no_intake(client, signed, slack_fakes, intake_stub):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)
    seen, _ = intake_stub

    body = json.dumps(_message_event(user="U0STRANGER", files=[PLAN_FILE])).encode()
    r = client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert r.status_code == 200
    assert seen == []
    assert slack_fakes.downloads == []
    [eph] = slack_fakes.ephemerals
    assert eph["user"] == "U0STRANGER"
    assert "stranger@else.com" in eph["text"]
    assert "don't know who you are" in eph["text"]


def test_user_from_another_org_is_unknown_here(client, signed, slack_fakes, intake_stub):
    """A real Proq user whose org did not install this workspace is a stranger."""
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    _register(client, "other@beta-build.com", "Beta Build")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)
    slack_fakes.emails["U0OTHER"] = "other@beta-build.com"
    seen, _ = intake_stub
    body = json.dumps(_message_event(user="U0OTHER", files=[PLAN_FILE])).encode()
    client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert seen == []
    assert len(slack_fakes.ephemerals) == 1


def test_message_in_unlinked_channel_is_ignored_but_mention_auto_links(client, signed, slack_fakes, intake_stub):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    seen, handle_request = intake_stub
    handle_request.project_id = pid

    # A plain file share in a channel nobody linked: not ours.
    body = json.dumps(_message_event(files=[PLAN_FILE], event_id="Ev1")).encode()
    client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert seen == []

    # Mentioning the bot with the file is an explicit ask: intake runs and the
    # channel gets linked to the project intake chose.
    env = _message_event(files=[PLAN_FILE], event_id="Ev2", text=f"<@{BOT_USER}> here is the site set")
    env["event"]["type"] = "app_mention"
    body = json.dumps(env).encode()
    client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert len(seen) == 1
    assert seen[0]["text"] == "here is the site set"
    with SessionLocal() as db:
        link = slack_repo.link_for_channel(db, me["organizationId"], TEAM, CHANNEL)
        assert link is not None and link.project_id == pid
        assert link.channel_name == "riverside-wtp"

    # The same post also arrives as a `message` event (Slack sends both); it
    # must not run intake a second time.
    dup = _message_event(files=[PLAN_FILE], event_id="Ev3", text=f"<@{BOT_USER}> here is the site set")
    body = json.dumps(dup).encode()
    client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert len(seen) == 1


def test_app_mention_without_files_still_reaches_intake(client, signed, slack_fakes, intake_stub):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)
    seen, _ = intake_stub
    env = _message_event(text=f"<@{BOT_USER}> where are we on the hydrants?")
    env["event"]["type"] = "app_mention"
    body = json.dumps(env).encode()
    client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert len(seen) == 1
    assert seen[0]["attachments"] == []
    assert seen[0]["text"] == "where are we on the hydrants?"


def test_bot_messages_and_missing_installation_are_ignored(client, signed, slack_fakes, intake_stub):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)
    seen, _ = intake_stub
    env = _message_event(files=[PLAN_FILE], event_id="Ev1")
    env["event"]["bot_id"] = "B0PROQ"
    body = json.dumps(env).encode()
    client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    env = _message_event(files=[PLAN_FILE], event_id="Ev2")
    env["team_id"] = "T0UNKNOWN"
    body = json.dumps(env).encode()
    client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert seen == []


def test_intake_not_wired_posts_honest_reply(client, signed, slack_fakes, monkeypatch):
    from app.services.inbound import intake

    monkeypatch.delattr(intake, "handle_request", raising=False)
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)
    body = json.dumps(_message_event(files=[PLAN_FILE])).encode()
    client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert slack_fakes.downloads == [PLAN_FILE["url_private_download"]]
    [msg] = slack_fakes.messages
    assert msg["channel"] == CHANNEL
    assert msg["thread_ts"] == "1700000000.000100"
    assert "not wired up yet" in msg["text"]


# --------------------------------------------------------------------------- #
# interactions: approve award
# --------------------------------------------------------------------------- #

def _approve_payload(value, user="U0PM"):
    return {
        "type": "block_actions",
        "team": {"id": TEAM, "domain": "alpha"},
        "user": {"id": user, "username": "pm", "team_id": TEAM},
        "channel": {"id": CHANNEL, "name": "riverside-wtp"},
        "message": {"ts": "1700000000.000300", "blocks": []},
        "container": {"type": "message", "message_ts": "1700000000.000300", "channel_id": CHANNEL},
        "response_url": "https://hooks.slack.com/actions/T0AAA/1/abc",
        "actions": [{"action_id": "approve_award", "block_id": "b1", "type": "button", "value": value}],
    }


def _post_interaction(client, payload):
    body = urlencode({"payload": json.dumps(payload)}).encode()
    headers = dict(_signed_headers(body), **{"Content-Type": "application/x-www-form-urlencoded"})
    return client.post("/api/webhooks/slack/interactions", content=body, headers=headers)


def test_approve_click_executes_approval_and_updates_card(client, signed, slack_fakes, monkeypatch):
    import app.services as services_pkg

    executed = []

    def execute(db, token, *, decided_by_email):
        executed.append((token, decided_by_email))
        return {"poNumbers": ["PO-1-1", "PO-1-2"], "title": "Riverside WTP: water utilities awarded"}

    monkeypatch.setattr(services_pkg, "approvals", SimpleNamespace(execute=execute), raising=False)
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    _install(me["organizationId"], me["id"])

    r = _post_interaction(client, _approve_payload("http://localhost:5173/#/approve/tok_abc-123"))
    assert r.status_code == 200
    assert executed == [("tok_abc-123", "pm@alpha-gc.com")]
    [upd] = slack_fakes.updates
    assert upd["channel"] == CHANNEL and upd["ts"] == "1700000000.000300"
    assert upd["blocks"][0]["type"] == "header"
    flat = json.dumps(upd["blocks"])
    assert "PO-1-1" in flat and "PO-1-2" in flat
    assert slack_fakes.ephemerals == []


def test_approve_click_from_unknown_user_is_refused(client, signed, slack_fakes, monkeypatch):
    import app.services as services_pkg

    executed = []
    monkeypatch.setattr(
        services_pkg, "approvals",
        SimpleNamespace(execute=lambda db, token, *, decided_by_email: executed.append(token)), raising=False,
    )
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    _install(me["organizationId"], me["id"])
    _post_interaction(client, _approve_payload("http://localhost:5173/#/approve/tok_abc", user="U0STRANGER"))
    assert executed == []
    assert slack_fakes.updates == []
    assert len(slack_fakes.ephemerals) == 1


def test_approve_click_with_unknown_token_reports_the_error(client, signed, slack_fakes):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    _install(me["organizationId"], me["id"])
    _post_interaction(client, _approve_payload("http://localhost:5173/#/approve/tok_abc"))
    assert slack_fakes.updates == []
    [eph] = slack_fakes.ephemerals
    assert "could not issue the award" in eph["text"]


def test_approve_click_failure_is_reported_ephemerally(client, signed, slack_fakes, monkeypatch):
    import app.services as services_pkg

    def execute(db, token, *, decided_by_email):
        raise ValueError("This approval link was already used.")

    monkeypatch.setattr(services_pkg, "approvals", SimpleNamespace(execute=execute), raising=False)
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    _install(me["organizationId"], me["id"])
    _post_interaction(client, _approve_payload("http://localhost:5173/#/approve/tok_abc"))
    assert slack_fakes.updates == []
    [eph] = slack_fakes.ephemerals
    assert "already used" in eph["text"]


def test_open_url_click_is_a_noop(client, signed, slack_fakes):
    payload = _approve_payload("x")
    payload["actions"][0]["action_id"] = "open_url"
    r = _post_interaction(client, payload)
    assert r.status_code == 200
    assert slack_fakes.updates == [] and slack_fakes.ephemerals == []


# --------------------------------------------------------------------------- #
# slash commands
# --------------------------------------------------------------------------- #

def _post_command(client, text, channel_id=CHANNEL, channel_name="riverside-wtp", team_id=TEAM):
    form = {"command": "/proq", "text": text, "team_id": team_id, "channel_id": channel_id,
            "channel_name": channel_name, "user_id": "U0PM", "response_url": "https://hooks.slack.com/x"}
    body = urlencode(form).encode()
    headers = dict(_signed_headers(body), **{"Content-Type": "application/x-www-form-urlencoded"})
    r = client.post("/api/webhooks/slack/commands", content=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_slash_link_and_status(client, signed, slack_fakes):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _new_project(client, headers, "Downtown Garage")
    _install(me["organizationId"], me["id"])

    assert "not linked" in _post_command(client, "status")["text"]
    out = _post_command(client, "link riverside")
    assert out["response_type"] == "ephemeral"
    assert "Riverside WTP" in out["text"]
    with SessionLocal() as db:
        link = slack_repo.link_for_channel(db, me["organizationId"], TEAM, CHANNEL)
        assert link.project_id == pid and link.channel_name == "riverside-wtp"
    out = _post_command(client, "status")
    assert "Riverside WTP" in out["text"]
    assert "Project created" in out["text"] or "activity" in out["text"]
    assert "could not find" in _post_command(client, "link nothing like this")["text"]
    assert "/proq link" in _post_command(client, "help")["text"]
    assert "not connected" in _post_command(client, "status", team_id="T0NOPE")["text"]


# --------------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------------- #

def test_oauth_callback_with_valid_state_installs_and_redirects(client, monkeypatch):
    monkeypatch.setattr(settings, "slack_client_id", "1.2")
    monkeypatch.setattr(settings, "slack_client_secret", "sekret")
    monkeypatch.setattr(settings, "slack_signing_secret", SECRET)
    exchanged = []

    def oauth_access(code):
        exchanged.append(code)
        return {"ok": True, "access_token": "xoxb-new", "bot_user_id": "U0BOT", "team": {"id": "T0NEW", "name": "Alpha GC"}}

    monkeypatch.setattr(slack_client, "oauth_access", oauth_access)
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")

    r = client.get("/api/slack/install-url", headers=headers)
    assert r.status_code == 200
    url = urlparse(r.json()["url"])
    assert url.netloc == "slack.com" and url.path == "/oauth/v2/authorize"
    q = parse_qs(url.query)
    assert q["client_id"] == ["1.2"]
    assert "chat:write" in q["scope"][0] and "users:read.email" in q["scope"][0]
    state = q["state"][0]
    assert slack_oauth.parse_state(state) == (me["organizationId"], me["id"])

    r = client.get(f"/api/webhooks/slack/oauth/callback?code=c0de&state={state}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/#/settings?slack=connected")
    assert exchanged == ["c0de"]

    status = client.get("/api/slack/status", headers=headers).json()
    assert status["installed"] and status["teamName"] == "Alpha GC" and status["teamId"] == "T0NEW"
    assert status["configured"] and status["missing"] == []
    assert "xoxb" not in r.text and "botToken" not in status


def test_oauth_callback_rejects_bad_or_expired_state(client, monkeypatch):
    called = []
    monkeypatch.setattr(slack_client, "oauth_access", lambda code: called.append(code))
    r = client.get("/api/webhooks/slack/oauth/callback?code=c0de&state=garbage")
    assert r.status_code == 400
    # A token for a different scope must not pass as install state.
    from app.core.security import create_scoped_token

    r = client.get(f"/api/webhooks/slack/oauth/callback?code=c0de&state={create_scoped_token('org:user', 'file:x', 10)}")
    assert r.status_code == 400
    expired = create_scoped_token("org:user", slack_oauth.STATE_SCOPE, -1)
    r = client.get(f"/api/webhooks/slack/oauth/callback?code=c0de&state={expired}")
    assert r.status_code == 400
    assert called == []


def test_oauth_callback_user_cancelled(client):
    state = slack_oauth.make_state("org", "user")
    r = client.get(f"/api/webhooks/slack/oauth/callback?error=access_denied&state={state}", follow_redirects=False)
    assert r.status_code == 302
    assert "slack=error" in r.headers["location"] and "access_denied" in r.headers["location"]


def test_status_and_install_url_unconfigured(auth):
    client, headers = auth
    status = client.get("/api/slack/status", headers=headers).json()
    assert status["configured"] is False and status["installed"] is False
    assert set(status["missing"]) == {"PROCUREAI_SLACK_CLIENT_ID", "PROCUREAI_SLACK_CLIENT_SECRET", "PROCUREAI_SLACK_SIGNING_SECRET"}
    assert client.get("/api/slack/install-url", headers=headers).status_code == 409


# --------------------------------------------------------------------------- #
# SlackNotifier
# --------------------------------------------------------------------------- #

def _notice(org_id, **kw):
    base = dict(
        org_id=org_id, kind="award.ready", title="Riverside WTP: water utilities award ready",
        lines=["Quotes leveled to the line: 5 of 7 suppliers", "Freight and lead time priced in: 14d / 16d"],
        actions=[
            notify.Action("Approve award", url="http://localhost:5173/#/approve/tok_1", style="primary"),
            notify.Action("See the comparison", url="http://localhost:5173/#/projects/riverside"),
        ],
    )
    base.update(kw)
    return notify.Notice(**base)


def test_notifier_renders_blocks_and_posts_to_linked_channel(client, slack_fakes):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)
    with SessionLocal() as db:
        notify_slack.SlackNotifier().notify(db, _notice(me["organizationId"], project_id=pid))
    [msg] = slack_fakes.messages
    assert msg["channel"] == CHANNEL and msg["thread_ts"] is None
    assert msg["text"] == "Riverside WTP: water utilities award ready"
    assert msg["blocks"] == [
        {"type": "header", "text": {"type": "plain_text", "text": "Riverside WTP: water utilities award ready", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "• Quotes leveled to the line: 5 of 7 suppliers\n• Freight and lead time priced in: 14d / 16d"}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Approve award", "emoji": True},
             "action_id": "approve_award", "value": "http://localhost:5173/#/approve/tok_1", "style": "primary"},
            {"type": "button", "text": {"type": "plain_text", "text": "See the comparison", "emoji": True},
             "action_id": "open_url", "url": "http://localhost:5173/#/projects/riverside"},
        ]},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Proq"}]},
    ]
    assert slack_blocks.approval_token_from(msg["blocks"][2]["elements"][0]["value"]) == "tok_1"


def test_notifier_replies_in_thread_for_slack_threadref(client, slack_fakes):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    _install(me["organizationId"], me["id"])
    thread = notify.ThreadRef(channel="slack", slack_channel_id="C0OTHER", slack_thread_ts="1700000000.000100")
    with SessionLocal() as db:
        notify_slack.SlackNotifier().notify(
            db, _notice(me["organizationId"], kind="intake.received", title="Got it", lines=["1 file"], actions=[], thread=thread)
        )
    [msg] = slack_fakes.messages
    assert msg["channel"] == "C0OTHER" and msg["thread_ts"] == "1700000000.000100"
    # No footer for non-milestone kinds, no actions block without actions.
    assert [b["type"] for b in msg["blocks"]] == ["header", "section"]


def test_notifier_is_noop_without_link_or_installation(client, slack_fakes):
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    with SessionLocal() as db:
        notify_slack.SlackNotifier().notify(db, _notice(me["organizationId"], project_id=pid))
    _install(me["organizationId"], me["id"])
    with SessionLocal() as db:
        notify_slack.SlackNotifier().notify(db, _notice(me["organizationId"], project_id=pid))
        notify_slack.SlackNotifier().notify(db, _notice(me["organizationId"], project_id=None))
    assert slack_fakes.messages == []


def test_notifier_is_registered_and_emit_isolates_failures(client, slack_fakes, monkeypatch):
    assert "slack" in notify.registered()
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Riverside WTP")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)

    def boom(*a, **k):
        raise slack_client.SlackError("not_in_channel", "chat.postMessage")

    monkeypatch.setattr(slack_client, "post_message", boom)
    with SessionLocal() as db:
        notify.emit(db, _notice(me["organizationId"], project_id=pid))  # must not raise


# --------------------------------------------------------------------------- #
# settings endpoints: org scoping
# --------------------------------------------------------------------------- #

def test_channel_links_are_org_scoped(client, monkeypatch):
    monkeypatch.setattr(slack_client, "auth_revoke", lambda token: None)
    a_headers, a = _register(client, "a@alpha-gc.com", "Alpha GC")
    b_headers, b = _register(client, "b@beta-build.com", "Beta Build")
    a_pid = _new_project(client, a_headers, "Riverside WTP")
    b_pid = _new_project(client, b_headers, "Beta Tower")
    _install(a["organizationId"], a["id"], team_id="T0A")
    _install(b["organizationId"], b["id"], team_id="T0B")

    r = client.put(f"/api/slack/channels/{CHANNEL}", headers=a_headers, json={"projectId": a_pid, "channelName": "riverside-wtp"})
    assert r.status_code == 200, r.text
    assert r.json()["projectId"] == a_pid and r.json()["projectName"] == "Riverside WTP"
    # B cannot link to A's project, and does not see A's channel.
    r = client.put("/api/slack/channels/C0BETA", headers=b_headers, json={"projectId": a_pid})
    assert r.status_code == 404
    assert client.get("/api/slack/channels", headers=b_headers).json() == []
    assert [c["channelId"] for c in client.get("/api/slack/channels", headers=a_headers).json()] == [CHANNEL]
    assert client.get("/api/slack/status", headers=b_headers).json()["channels"] == []
    # B cannot unlink A's channel.
    assert client.delete(f"/api/slack/channels/{CHANNEL}", headers=b_headers).status_code == 404
    assert len(client.get("/api/slack/channels", headers=a_headers).json()) == 1
    # Relink then unlink as A.
    r = client.put(f"/api/slack/channels/{CHANNEL}", headers=a_headers, json={"projectId": a_pid})
    assert r.status_code == 200 and r.json()["channelName"] == "riverside-wtp"
    assert client.delete(f"/api/slack/channels/{CHANNEL}", headers=a_headers).status_code == 204
    assert client.get("/api/slack/channels", headers=a_headers).json() == []
    # Uninstall A: B's installation is untouched.
    assert client.delete("/api/slack/installation", headers=a_headers).status_code == 204
    assert client.get("/api/slack/status", headers=a_headers).json()["installed"] is False
    assert client.get("/api/slack/status", headers=b_headers).json()["installed"] is True
    assert client.delete("/api/slack/installation", headers=a_headers).status_code == 404
    assert client.get("/api/slack/status").status_code == 401


def test_link_requires_installation(auth):
    client, headers = auth
    pid = _new_project(client, headers, "Riverside WTP")
    r = client.put(f"/api/slack/channels/{CHANNEL}", headers=headers, json={"projectId": pid})
    assert r.status_code == 409


def test_events_and_clicks_without_an_installation_are_dropped_with_a_log_line(client, signed, slack_fakes, intake_stub, caplog):
    """No installation for the team (a dev server with no Slack app): the
    request is acknowledged, nothing runs, and the log says why."""
    import logging

    seen, _ = intake_stub
    with caplog.at_level(logging.INFO, logger="procureai.slack"):
        body = json.dumps(_message_event(files=[PLAN_FILE], event_id="EvNoInstall")).encode()
        assert client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body)).status_code == 200
        assert _post_interaction(client, {
            "type": "block_actions", "team": {"id": TEAM}, "user": {"id": "U0PM", "team_id": TEAM},
            "channel": {"id": CHANNEL}, "message": {"ts": "1.2"},
            "actions": [{"type": "button", "action_id": "approve_award", "value": "http://x/#/approve/tok"}],
        }).status_code == 200
    assert seen == [] and slack_fakes.downloads == []
    assert "slack event EvNoInstall (message): ignored:no_installation" in caplog.text
    assert f"slack interaction from team {TEAM}: ignored:no_installation" in caplog.text


def test_url_verification_is_answered_before_the_signature_check(client, monkeypatch):
    """Slack sends the handshake when you first save the Events request URL.

    That happens before the app exists, so its signing secret cannot be
    configured yet: verifying the signature first would make the URL
    impossible to verify on any deployment that refuses unsigned requests
    (production does). The echo carries no data and performs no action.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "slack_signing_secret", "", raising=False)
    monkeypatch.setattr(settings, "env", "production", raising=False)
    monkeypatch.setattr(settings, "allow_unsigned_webhooks", False, raising=False)
    r = client.post(
        "/api/webhooks/slack/events",
        json={"type": "url_verification", "challenge": "c0ffee"},
    )
    assert r.status_code == 200 and r.text == "c0ffee"

    # Anything else still needs a valid signature.
    r = client.post("/api/webhooks/slack/events", json={"type": "event_callback", "event": {}})
    assert r.status_code == 401


def test_linked_channel_names_the_project_instead_of_the_channel(client, signed, slack_fakes, intake_stub):
    """A channel linked with /proq link must route work to THAT project.

    Passing only the channel name let intake resolve by name, which invented a
    project called after the channel ("all-proq") and filed the plan set where
    nobody was looking, beside the real one.
    """
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    pid = _new_project(client, headers, "Southside Meadows")
    _install(me["organizationId"], me["id"])
    _link(me["organizationId"], CHANNEL, pid)
    seen, _ = intake_stub

    body = json.dumps(_message_event(files=[PLAN_FILE])).encode()
    r = client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert r.status_code == 200
    assert len(seen) == 1 and seen[0]["project_id"] == pid


def test_unlinked_channel_leaves_the_project_to_intake(client, signed, slack_fakes, intake_stub):
    """No link, no opinion: intake resolves and the channel is linked after."""
    headers, me = _register(client, "pm@alpha-gc.com", "Alpha GC")
    _install(me["organizationId"], me["id"])
    seen, _ = intake_stub

    env = _message_event(files=[PLAN_FILE], text=f"<@{BOT_USER}> here is the set")
    env["event"]["type"] = "app_mention"
    body = json.dumps(env).encode()
    r = client.post("/api/webhooks/slack/events", content=body, headers=_signed_headers(body))
    assert r.status_code == 200
    assert len(seen) == 1 and seen[0]["project_id"] is None
