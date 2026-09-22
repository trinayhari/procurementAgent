"""Autonomous supplier follow-ups (services/rfq/followups.py).

conftest disables the scheduler job (PROCUREAI_FOLLOWUP_ENABLED=false), so
every test drives `run_due` / `chase_rfq` directly with an injected clock and
a UTC send window. Sends go through a recording sender; nothing leaves.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.db import SessionLocal
from app.models.rfq import Rfq
from app.repositories import audit as audit_repo
from app.repositories import purchase_decisions as decisions_repo
from app.repositories import quotes as quotes_repo
from app.repositories import rfqs as rfqs_repo
from app.services import notify
from app.services.rfq import followups
from app.services.rfq import sender as rfq_sender
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search

UTC = timezone.utc
# Monday 10:00 UTC. First nudge (48h) lands Wednesday 10:00, second (96h)
# Friday 10:00: all weekdays, all inside the 8-17 window.
SENT = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
H = timedelta(hours=1)
EM_DASH = chr(0x2014)  # never in Proq copy


class _Recorder:
    mocked = True

    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    def send(self, to, subject, body, *, from_addr, cc=None, thread_id=None, in_reply_to=None, attachments=None):
        if to in self.fail_for:
            raise RuntimeError("mailbox rejected")
        self.sent.append({"to": to, "subject": subject, "body": body, "from": from_addr,
                          "cc": cc, "thread_id": thread_id, "in_reply_to": in_reply_to})
        return rfq_sender.SentMessage(message_id=f"<fu-{len(self.sent)}@proq>", thread_id=thread_id or "t")


class _FakeNotifier:
    name = "test"

    def __init__(self):
        self.notices = []

    def notify(self, db, notice):
        self.notices.append(notice)


@pytest.fixture()
def policy(monkeypatch):
    monkeypatch.setattr(settings, "followup_first_delay_hours", 48)
    monkeypatch.setattr(settings, "followup_second_delay_hours", 96)
    monkeypatch.setattr(settings, "followup_max", 2)
    monkeypatch.setattr(settings, "followup_send_hour_start", 8)
    monkeypatch.setattr(settings, "followup_send_hour_end", 17)
    monkeypatch.setattr(settings, "followup_weekdays_only", True)


@pytest.fixture()
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a: rec)
    return rec


@pytest.fixture()
def notifier():
    fake = _FakeNotifier()
    notify.register(fake)
    yield fake
    notify.reset()


def _org(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["organizationId"]


def _sent_rfq(client, headers, pid, n=2, sent_at=SENT):
    """A sent RFQ whose recipients carry an RFC Message-ID (as stream A's
    sender records it) and whose send time is pinned to `sent_at`."""
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:n])
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "Awaiting", r.text
    # The RFQ itself went through whatever sender is patched in; only nudges
    # are of interest to the tests.
    sender = rfq_sender.get_sender()  # the same recorder whichever signature
    if hasattr(sender, "sent"):
        sender.sent.clear()
    org_id = _org(client, headers)
    with SessionLocal() as db:
        row = db.get(Rfq, rfq["id"])
        recipients = json.loads(row.recipients)
        for i, rcp in enumerate(recipients):
            rcp["messageId"] = f"<rfq-{i}@proq>"
        row.recipients = json.dumps(recipients)
        row.sent_at = sent_at.replace(tzinfo=None)
        db.commit()
    return org_id, bom_id, client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()


def _run(now):
    with SessionLocal() as db:
        return followups.run_due(db, now=now, tz=UTC)


def _recipients(org_id, rfq_id):
    with SessionLocal() as db:
        return rfqs_repo.get_rfq(db, org_id, rfq_id)["recipients"]


def _save(org_id, rfq_id, recipients):
    with SessionLocal() as db:
        rfqs_repo.save_recipients(db, org_id, rfq_id, recipients)


# ------------------------------------------------------------------ policy
def test_nothing_is_due_before_the_first_delay(project, policy, recorder):
    client, headers, pid = project
    org_id, _, rfq = _sent_rfq(client, headers, pid)
    s = _run(SENT + 47 * H)
    assert s.rfqs_scanned == 1 and s.nudges_sent == 0 and recorder.sent == []
    assert all(not r.get("followups") for r in _recipients(org_id, rfq["id"]))


def test_first_nudge_goes_out_after_the_delay_inside_hours_and_only_once(project, policy, recorder):
    client, headers, pid = project
    org_id, _, rfq = _sent_rfq(client, headers, pid)
    s = _run(SENT + 48 * H)
    assert s.nudges_sent == 2 and s.errors == []
    assert sorted(m["to"] for m in recorder.sent) == sorted(r["email"] for r in rfq["recipients"])
    for r in _recipients(org_id, rfq["id"]):
        assert [(f["n"], bool(f["messageId"])) for f in r["followups"]] == [(1, True)]
        assert r["followups"][0]["sentAt"] == (SENT + 48 * H).isoformat()
    # The next tick, still before the second delay, sends nothing more.
    s = _run(SENT + 49 * H)
    assert s.nudges_sent == 0 and len(recorder.sent) == 2


@pytest.mark.parametrize("now, reason", [
    (SENT + 48 * H + 8 * H, "18:00 is after the window"),
    (SENT + 72 * H - 3 * H, "07:00 is before the window"),
    (SENT + 5 * 24 * H, "Saturday"),
])
def test_nothing_goes_out_outside_hours_or_on_a_weekend(project, policy, recorder, now, reason):
    client, headers, pid = project
    _sent_rfq(client, headers, pid)
    s = _run(now)
    assert s.nudges_sent == 0 and recorder.sent == [], reason
    assert s.skipped_outside_hours == 2, reason


def test_weekend_sends_when_weekdays_only_is_off(project, policy, recorder, monkeypatch):
    client, headers, pid = project
    _sent_rfq(client, headers, pid)
    monkeypatch.setattr(settings, "followup_weekdays_only", False)
    assert _run(SENT + 5 * 24 * H).nudges_sent == 2


def test_second_nudge_after_the_second_delay_and_never_a_third(project, policy, recorder):
    client, headers, pid = project
    org_id, _, rfq = _sent_rfq(client, headers, pid, n=1)
    assert _run(SENT + 48 * H).nudges_sent == 1
    assert _run(SENT + 95 * H).nudges_sent == 0
    assert _run(SENT + 96 * H).nudges_sent == 1
    [r] = _recipients(org_id, rfq["id"])
    assert [f["n"] for f in r["followups"]] == [1, 2]
    # Exhausted: days later, nothing more, on the scheduler or by force.
    assert _run(SENT + 200 * H).nudges_sent == 0
    with SessionLocal() as db:
        assert followups.chase_rfq(db, org_id, rfq["id"], now=SENT + 200 * H, force=True).nudges_sent == 0
    assert len(recorder.sent) == 2
    assert [m["subject"] for m in recorder.sent] == [f"Re: {rfq['subject']}"] * 2


def test_a_late_first_nudge_keeps_the_spacing_before_the_second(project, policy, recorder):
    """Scheduler was down until after the second delay: the recipient gets
    nudge 1 now (Friday), and nudge 2 only 48h of spacing later (that lands
    on a Sunday, so Monday), not on the next tick."""
    client, headers, pid = project
    org_id, _, rfq = _sent_rfq(client, headers, pid, n=1)
    assert _run(SENT + 96 * H).nudges_sent == 1
    assert _run(SENT + 97 * H).nudges_sent == 0
    assert _run(SENT + 96 * H + 72 * H).nudges_sent == 1
    assert [f["n"] for f in _recipients(org_id, rfq["id"])[0]["followups"]] == [1, 2]


def test_replied_recipients_are_skipped_on_either_signal(project, policy, recorder):
    client, headers, pid = project
    org_id, bom_id, rfq = _sent_rfq(client, headers, pid)
    a, b = _recipients(org_id, rfq["id"])
    a["repliedAt"] = (SENT + 3 * H).isoformat()
    _save(org_id, rfq["id"], [a, b])
    with SessionLocal() as db:
        quotes_repo.create_quote(
            db, org_id, project_id=pid, package=bom_id, package_label="Hydrants Package",
            rfq_id=rfq["id"], supplier_name=b["name"], supplier_email=b["email"].upper(),
            total=1000.0, source="test",
        )
    s = _run(SENT + 48 * H)
    assert s.nudges_sent == 0 and recorder.sent == []
    status = client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}/followups", headers=headers).json()
    assert [r["replied"] for r in status["recipients"]] == [True, True]
    assert status["recipients"][0]["repliedAt"] == a["repliedAt"]
    assert all(r["nextDueAt"] is None for r in status["recipients"])


def test_awarded_packages_are_not_chased(project, policy, recorder):
    client, headers, pid = project
    org_id, bom_id, rfq = _sent_rfq(client, headers, pid)
    with SessionLocal() as db:
        decisions_repo.add_decision(
            db, org_id, pid, bom_id, "Hydrants Package",
            summary={"supplierIds": ["x"], "total": 1}, selections={}, strategy=None, decided_by=None,
        )
        db.commit()
    assert _run(SENT + 48 * H).nudges_sent == 0 and recorder.sent == []
    status = client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}/followups", headers=headers).json()
    assert all(r["nextDueAt"] is None for r in status["recipients"])


# ------------------------------------------------------------ durability
def test_a_stale_intent_is_retried_once_and_a_fresh_one_is_left_alone(project, policy, recorder):
    client, headers, pid = project
    org_id, _, rfq = _sent_rfq(client, headers, pid)
    now = SENT + 48 * H
    a, b = _recipients(org_id, rfq["id"])
    # a: the process died 11 minutes ago between writing the intent and sending.
    a["followups"] = [{"n": 1, "sentAt": (now - 11 * timedelta(minutes=1)).isoformat(), "messageId": None}]
    # b: another worker wrote its intent 2 minutes ago and is still sending.
    b["followups"] = [{"n": 1, "sentAt": (now - 2 * timedelta(minutes=1)).isoformat(), "messageId": None}]
    _save(org_id, rfq["id"], [a, b])
    s = _run(now)
    assert s.nudges_sent == 1 and [m["to"] for m in recorder.sent] == [a["email"]]
    a2, b2 = _recipients(org_id, rfq["id"])
    assert [(f["n"], f["messageId"]) for f in a2["followups"]] == [(1, "<fu-1@proq>")]
    assert a2["followups"][0]["sentAt"] == now.isoformat()
    assert b2["followups"] == b["followups"]
    # Running again does not send a second copy to either.
    assert _run(now + timedelta(minutes=1)).nudges_sent == 0


def test_intent_is_persisted_before_the_send_and_a_failed_send_keeps_it(project, policy, monkeypatch):
    client, headers, pid = project
    org_id, _, rfq = _sent_rfq(client, headers, pid, n=1)
    [rcp] = rfq["recipients"]
    seen = []

    class Crash:
        mocked = True

        def send(self, *a, **kw):
            seen.append(_recipients(org_id, rfq["id"])[0]["followups"])
            raise RuntimeError("smtp down")

    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a: Crash())
    now = SENT + 48 * H
    s = _run(now)
    assert s.nudges_sent == 0 and len(s.errors) == 1 and rcp["email"] in s.errors[0]
    # The intent was on disk before the sender was called, and survives the failure.
    assert seen == [[{"n": 1, "sentAt": now.isoformat(), "messageId": None}]]
    assert _recipients(org_id, rfq["id"])[0]["followups"] == seen[0]
    # Retried after the intent times out, not before.
    rec = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a: rec)
    assert _run(now + timedelta(minutes=5)).nudges_sent == 0
    assert _run(now + timedelta(minutes=11)).nudges_sent == 1


# --------------------------------------------------------------- the email
def test_nudge_replies_in_the_original_thread_and_ccs_the_sender(project, policy, recorder):
    client, headers, pid = project
    r = client.patch("/api/auth/me", headers=headers, json={"ccEmail": "copies@example.com"})
    assert r.status_code == 200, r.text
    org_id, _, rfq = _sent_rfq(client, headers, pid, n=1)
    [rcp] = _recipients(org_id, rfq["id"])  # the stored dict, not the API shape
    assert _run(SENT + 48 * H).nudges_sent == 1
    [m] = recorder.sent
    assert m["to"] == rcp["email"]
    assert m["subject"] == f"Re: {rfq['subject']}"
    assert m["in_reply_to"] == rcp["messageId"] == "<rfq-0@proq>"
    assert m["thread_id"] == rcp["threadId"]
    assert "@" in m["from"]
    assert m["cc"] == "copies@example.com"
    body = m["body"]
    assert "Hydrants Package" in body
    assert "reply to this email with your pricing" in body
    assert EM_DASH not in body  # the subject inherits the RFQ's own, for threading
    # Our own message id is remembered so ingest never parses the nudge as a reply.
    assert "<fu-1@proq>" in _recipients(org_id, rfq["id"])[0]["outboundMessageIds"]


def test_draft_mentions_the_need_by_date_and_nudge_number():
    rfq = {"subject": "RFQ: Rebar", "pkg": "Rebar", "needBy": "October 3"}
    subject, body = followups.draft_followup(rfq, {"email": "a@b.co", "name": "Acme"}, 2)
    assert subject == "Re: RFQ: Rebar"
    assert "October 3" in body and "Rebar" in body and "again" in body
    assert EM_DASH not in body
    _, lead = followups.draft_followup(rfq, {"email": "a@b.co"}, 1, outstanding="lead_time")
    assert "lead time" in lead and "pricing and lead time" not in lead


def test_audit_entry_and_notice_are_emitted_per_nudge(project, policy, recorder, notifier):
    client, headers, pid = project
    org_id, _, rfq = _sent_rfq(client, headers, pid, n=1)
    [rcp] = rfq["recipients"]
    assert _run(SENT + 48 * H).nudges_sent == 1
    with SessionLocal() as db:
        events = audit_repo.list_events(db, org_id, project_id=pid, action="rfq.followup_sent")
    assert len(events) == 1
    ev = events[0]
    assert ev["entityId"] == rfq["id"] and ev["actorId"] == "system"
    assert ev["detail"]["email"] == rcp["email"] and ev["detail"]["n"] == 1 and ev["detail"]["mock"] is True
    [n] = notifier.notices
    assert n.kind == "followup.sent" and n.org_id == org_id and n.project_id == pid
    assert n.title == f"Hydrants Package: chased {rcp['name']} (nudge 1 of 2)"
    assert n.meta == {"rfqId": rfq["id"], "email": rcp["email"], "n": 1}


def test_one_dead_address_does_not_stop_the_others(project, policy, monkeypatch):
    client, headers, pid = project
    org_id, _, rfq = _sent_rfq(client, headers, pid)
    a, b = rfq["recipients"]
    rec = _Recorder(fail_for={a["email"]})
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a: rec)
    s = _run(SENT + 48 * H)
    assert s.nudges_sent == 1 and len(s.errors) == 1 and [m["to"] for m in rec.sent] == [b["email"]]


def test_tick_runs_on_its_own_session(project, policy, recorder):
    client, headers, pid = project
    _sent_rfq(client, headers, pid)
    followups.tick()  # real clock: nothing due yet, and it must not raise


# --------------------------------------------------------------- endpoints
def test_followup_status_endpoint_reports_per_recipient_state(project, policy, recorder):
    client, headers, pid = project
    org_id, _, rfq = _sent_rfq(client, headers, pid)
    url = f"/api/projects/{pid}/rfqs/{rfq['id']}/followups"
    body = client.get(url, headers=headers).json()
    assert body["rfqId"] == rfq["id"] and body["max"] == 2
    assert [r["email"] for r in body["recipients"]] == [r["email"] for r in rfq["recipients"]]
    for r in body["recipients"]:
        assert r["supplierName"] and r["sentAt"] == SENT.isoformat()
        assert r["repliedAt"] is None and r["replied"] is False and r["followups"] == []
        assert r["nextDueAt"] == (SENT + 48 * H).isoformat()
    _run(SENT + 48 * H)
    body = client.get(url, headers=headers).json()
    for r in body["recipients"]:
        assert [f["n"] for f in r["followups"]] == [1]
        assert r["nextDueAt"] == (SENT + 96 * H).isoformat()
    assert client.get(f"/api/projects/{pid}/rfqs/nope/followups", headers=headers).status_code == 404


def test_manual_run_forces_a_nudge_now_but_respects_the_max(project, policy, recorder, notifier):
    client, headers, pid = project
    org_id, bom_id, rfq = _sent_rfq(client, headers, pid, sent_at=datetime.now(UTC))
    url = f"/api/projects/{pid}/rfqs/{rfq['id']}/followups/run"
    # Minutes after the send, whatever the hour: chased anyway.
    r = client.post(url, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["nudgesSent"] == 2 and r.json()["errors"] == []
    assert [[f["n"] for f in x["followups"]] for x in r.json()["recipients"]] == [[1], [1]]
    assert client.post(url, headers=headers).json()["nudgesSent"] == 2
    assert client.post(url, headers=headers).json()["nudgesSent"] == 0
    assert len(recorder.sent) == 4 and len(notifier.notices) == 4
    # A manual chase is audited to the person who clicked, not "system".
    with SessionLocal() as db:
        events = audit_repo.list_events(db, org_id, project_id=pid, action="rfq.followup_sent")
    assert {e["actorEmail"] for e in events} == {"pm@example.com"}
    # A draft cannot be chased; another org's RFQ does not exist.
    draft = generate_rfq(client, headers, pid, bom_id, [rfq["recipients"][0]["supplierId"]])
    assert client.post(f"/api/projects/{pid}/rfqs/{draft['id']}/followups/run", headers=headers).status_code == 409
    other = client.post("/api/auth/register", json={"email": "x@other.com", "password": "password123", "name": "X"}).json()
    oh = {"Authorization": f"Bearer {other['accessToken']}"}
    assert client.post(url, headers=oh).status_code == 404
