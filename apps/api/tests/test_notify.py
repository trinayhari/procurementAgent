"""The notify bus and its built-in channels: fan-out isolation, the email
channel's thread resolution (intake row, explicit ThreadRef, org fallback,
nobody to address), and the activity-feed channel."""
import uuid

import pytest

from app.db import SessionLocal
from app.models.inbound_email import InboundEmail
from app.repositories import events as events_repo
from app.services import notify
from app.services.notify import kinds
from app.services.notify import email as email_channel
from app.services.notify.activity import ActivityNotifier
from app.services.notify.email import EmailNotifier, render
from app.services.rfq.sender import SentMessage


class _Recorder:
    mocked = True

    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, *, from_addr, cc=None, thread_id=None,
             in_reply_to=None, attachments=None):
        self.sent.append({"to": to, "subject": subject, "body": body,
                          "in_reply_to": in_reply_to, "from_addr": from_addr})
        return SentMessage(message_id=f"rec-{len(self.sent)}", thread_id="t")


class _Boom:
    name = "boom"

    def notify(self, db, notice):
        raise RuntimeError("channel down")


class _Memo:
    name = "memo"

    def __init__(self):
        self.seen = []

    def notify(self, db, notice):
        self.seen.append(notice)


@pytest.fixture()
def bus():
    """A clean registry for the test, restored afterwards (main's startup
    installs the real channels on the shared module)."""
    before = list(notify._NOTIFIERS)
    notify.reset()
    yield
    notify.reset()
    for n in before:
        notify.register(n)


def _notice(org_id="org-a", project_id="p1", **kw):
    base = dict(org_id=org_id, project_id=project_id, kind=kinds.RFQ_SENT,
                title="Riverside: RFQ sent", lines=["3 suppliers asked to quote"])
    base.update(kw)
    return notify.Notice(**base)


def _intake_row(org_id, project_id, **kw):
    fields = dict(
        id=uuid.uuid4().hex, organization_id=org_id, provider_message_id=uuid.uuid4().hex,
        rfc_message_id="<intake-1@customer.example>", from_email="pm@customer.example",
        subject="Riverside plan set", kind="intake", project_id=project_id,
    )
    fields.update(kw)
    return InboundEmail(**fields)


# ------------------------------------------------------------------ the bus

def test_emit_fans_out_and_isolates_a_failing_channel(bus):
    memo = _Memo()
    notify.register(_Boom())
    notify.register(memo)
    notify.emit(None, _notice())  # the dead channel must not break the caller
    assert [n.kind for n in memo.seen] == [kinds.RFQ_SENT]


def test_register_is_idempotent_per_name(bus):
    a, b = _Memo(), _Memo()
    notify.register(a)
    notify.register(b)  # same name replaces, never duplicates
    assert notify.registered() == ["memo"]
    notify.emit(None, _notice())
    assert not a.seen and len(b.seen) == 1


def test_startup_installs_email_and_activity_channels(client):
    assert {"email", "activity"} <= set(notify.registered())


def test_kinds_are_dotted_and_unique():
    assert len(set(kinds.ALL)) == len(kinds.ALL)
    assert all("." in k for k in kinds.ALL)


# --------------------------------------------------------------- rendering

def test_render_is_plain_text_with_bullets_and_action_links():
    body = render(_notice(actions=[notify.Action("Approve award", url="https://app/#/approve/t")]))
    assert body.splitlines()[0] == "Riverside: RFQ sent"
    assert "- 3 suppliers asked to quote" in body
    assert "Approve award: https://app/#/approve/t" in body
    assert body.rstrip().endswith("Proq")
    assert "\u2014" not in body  # no em dashes in customer copy


# ----------------------------------------------------------- email channel

def test_email_replies_in_the_intake_thread(project, monkeypatch):
    client, headers, pid = project
    org_id = client.get("/api/auth/me", headers=headers).json()["organizationId"]
    with SessionLocal() as db:
        db.add(_intake_row(org_id, pid, provider_message_id="am-msg-9"))
        db.commit()
    rec = _Recorder()
    monkeypatch.setattr(email_channel, "get_sender", lambda *a: rec)
    with SessionLocal() as db:
        EmailNotifier().notify(db, _notice(org_id=org_id, project_id=pid))
    (m,) = rec.sent
    assert m["to"] == "pm@customer.example"
    assert m["subject"] == "Re: Riverside plan set"
    # The provider's id threads the reply; the RFC Message-ID is the fallback.
    assert m["in_reply_to"] == "am-msg-9"


def test_email_prefers_the_latest_intake_and_falls_back_to_rfc_id(project, monkeypatch):
    client, headers, pid = project
    org_id = client.get("/api/auth/me", headers=headers).json()["organizationId"]
    from datetime import datetime, timedelta
    old = datetime(2026, 1, 1)
    with SessionLocal() as db:
        db.add(_intake_row(org_id, pid, from_email="old@customer.example", received_at=old))
        db.add(_intake_row(org_id, pid, from_email="new@customer.example",
                           provider_message_id="", rfc_message_id="<new@customer>",
                           subject="Re: Riverside plan set", received_at=old + timedelta(days=1)))
        db.commit()
    rec = _Recorder()
    monkeypatch.setattr(email_channel, "get_sender", lambda *a: rec)
    with SessionLocal() as db:
        EmailNotifier().notify(db, _notice(org_id=org_id, project_id=pid))
    (m,) = rec.sent
    assert m["to"] == "new@customer.example"
    assert m["in_reply_to"] == "<new@customer>"
    assert m["subject"] == "Re: Riverside plan set"  # not "Re: Re: ..."


def test_email_uses_an_explicit_thread_ref_over_the_intake_row(project, monkeypatch):
    client, headers, pid = project
    org_id = client.get("/api/auth/me", headers=headers).json()["organizationId"]
    with SessionLocal() as db:
        db.add(_intake_row(org_id, pid))
        db.commit()
    rec = _Recorder()
    monkeypatch.setattr(email_channel, "get_sender", lambda *a: rec)
    ref = notify.ThreadRef(channel="email", email_message_id="<x@y>",
                           email_address="super@customer.example", email_subject="Addendum 2")
    with SessionLocal() as db:
        EmailNotifier().notify(db, _notice(org_id=org_id, project_id=pid, thread=ref))
    (m,) = rec.sent
    assert (m["to"], m["in_reply_to"], m["subject"]) == ("super@customer.example", "<x@y>", "Re: Addendum 2")


def test_email_falls_back_to_the_orgs_first_user(project, monkeypatch):
    client, headers, pid = project
    org_id = client.get("/api/auth/me", headers=headers).json()["organizationId"]
    rec = _Recorder()
    monkeypatch.setattr(email_channel, "get_sender", lambda *a: rec)
    with SessionLocal() as db:
        EmailNotifier().notify(db, _notice(org_id=org_id, project_id=pid))
    (m,) = rec.sent
    assert m["to"] == "pm@example.com"
    assert m["in_reply_to"] is None
    assert m["subject"] == "Riverside: RFQ sent"


def test_email_ignores_another_orgs_intake_row(client, monkeypatch):
    """An intake row for the same project id in another org never becomes
    the reply target."""
    r = client.post("/api/auth/register", json={"email": "a@alpha.example", "password": "password123", "name": "A"})
    ha = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    r = client.post("/api/auth/register", json={"email": "b@beta.example", "password": "password123", "name": "B"})
    hb = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    org_a = client.get("/api/auth/me", headers=ha).json()["organizationId"]
    org_b = client.get("/api/auth/me", headers=hb).json()["organizationId"]
    pid = client.post("/api/projects", headers=ha, json={"name": "Shared", "loc": "x", "type": "Commercial"}).json()["id"]
    with SessionLocal() as db:
        db.add(_intake_row(org_b, pid, from_email="pm@beta-customer.example"))
        db.commit()
    rec = _Recorder()
    monkeypatch.setattr(email_channel, "get_sender", lambda *a: rec)
    with SessionLocal() as db:
        EmailNotifier().notify(db, _notice(org_id=org_a, project_id=pid))
    assert [m["to"] for m in rec.sent] == ["a@alpha.example"]


def test_email_skips_when_the_org_has_nobody(client, monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(email_channel, "get_sender", lambda *a: rec)
    with SessionLocal() as db:
        EmailNotifier().notify(db, _notice(org_id="no-such-org", project_id=None))
    assert rec.sent == []


def test_email_sender_shim_accepts_both_signatures(project, monkeypatch):
    """`get_sender(db, org_id)` (AgentMail, one inbox per org) is tried first;
    the zero-arg form is the pre-merge fallback."""
    client, headers, pid = project
    org_id = client.get("/api/auth/me", headers=headers).json()["organizationId"]
    calls = []
    rec = _Recorder()

    def per_org(db, org):
        calls.append(org)
        return rec

    monkeypatch.setattr(email_channel, "get_sender", per_org)
    with SessionLocal() as db:
        EmailNotifier().notify(db, _notice(org_id=org_id, project_id=pid))
    assert calls == [org_id] and len(rec.sent) == 1


# -------------------------------------------------------- activity channel

def test_activity_channel_writes_the_project_feed(project):
    client, headers, pid = project
    org_id = client.get("/api/auth/me", headers=headers).json()["organizationId"]
    with SessionLocal() as db:
        ActivityNotifier().notify(db, _notice(
            org_id=org_id, project_id=pid, kind=kinds.AWARD_READY,
            title="Test Project: Hydrants award ready",
            lines=["Quotes leveled to the line: 3 of 3 suppliers", "Lead time 14d / 16d"],
        ))
        ActivityNotifier().notify(db, _notice(org_id=org_id, project_id=None))  # no project: skipped
        feed = events_repo.list_for_project(db, org_id, pid)
    top = feed[0]
    assert top["title"] == "Test Project: Hydrants award ready"
    assert top["meta"] == "Quotes leveled to the line: 3 of 3 suppliers · Lead time 14d / 16d"
    assert (top["icon"], top["tone"]) == ("check", "ai")
    assert sum(1 for e in feed if e["title"] == "Riverside: RFQ sent") == 0
