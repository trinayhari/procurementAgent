"""POST /api/webhooks/agentmail: signature checks, idempotency, inbox to org
mapping, attachment storage, the stored row and the background handler."""
import base64
import json
import time

import pytest

from app.config import settings
from app.db import SessionLocal
from app.models.inbound_email import InboundEmail
from app.models.organization import Organization
from app.api.routes import webhooks_agentmail
from app.services import inbound
from app.services.email import agentmail_client
from tests.agentmail_fakes import FakeAgentMail

SECRET = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
INBOX = "acme@proq.tryproq.dev"


def _event(mid="<r1@supplier.example>", inbox=INBOX, thread="thr_1", attachments=None, **over):
    message = {
        "inbox_id": inbox, "thread_id": thread, "message_id": mid, "labels": ["received"],
        "timestamp": "2026-09-16T15:00:00Z",
        "from": "Sales Team <Sales@Pipe.co>", "to": [f"Proq for Acme <{inbox}>"],
        "cc": ["pm@own.com"], "subject": "Re: RFQ: Water",
        "text": "Quote $52,000 total\n\nOn Tue Proq wrote:\n> please quote",
        "extracted_text": "Quote $52,000 total", "html": "<p>Quote $52,000 total</p>",
        "in_reply_to": "<m1@agentmail.to>", "references": ["<m1@agentmail.to>"],
        "headers": {"message-id": mid},
        "attachments": attachments or [], "size": 100,
    }
    message.update(over)
    return {"type": "event", "event_type": "message.received", "event_id": "evt_1",
            "message": message, "thread": {"inbox_id": inbox, "thread_id": thread}}


def _signed(body: bytes, secret=SECRET, ts=None):
    ts = str(int(ts if ts is not None else time.time()))
    return {"svix-id": "msg_1", "svix-timestamp": ts,
            "svix-signature": agentmail_client.sign_payload(secret, "msg_1", ts, body)}


@pytest.fixture()
def org_inbox(auth):
    """The test org owns INBOX. Returns (client, headers, org_id)."""
    client, headers = auth
    org_id = client.get("/api/auth/me", headers=headers).json()["organizationId"]
    db = SessionLocal()
    try:
        db.get(Organization, org_id).agentmail_inbox_id = INBOX
        db.commit()
    finally:
        db.close()
    return client, headers, org_id


@pytest.fixture()
def handled(monkeypatch):
    """Capture the rows handed to services.inbound.handle instead of running it."""
    seen = []
    monkeypatch.setattr(inbound, "handle", lambda db, row: seen.append(row.provider_message_id))
    return seen


def _rows():
    db = SessionLocal()
    try:
        return [r for r in db.query(InboundEmail).all()]
    finally:
        db.close()


# ---------------------------------------------------------------- signature
def test_signed_delivery_is_accepted_and_bad_signatures_rejected(org_inbox, handled, monkeypatch):
    client, headers, org_id = org_inbox
    monkeypatch.setattr(settings, "agentmail_webhook_secret", SECRET)
    body = json.dumps(_event()).encode()
    assert client.post("/api/webhooks/agentmail", content=body, headers=_signed(body)).status_code == 200
    assert client.post("/api/webhooks/agentmail", content=body).status_code == 401  # no headers
    assert client.post("/api/webhooks/agentmail", content=body + b" ",
                       headers=_signed(body)).status_code == 401  # tampered
    assert client.post("/api/webhooks/agentmail", content=body,
                       headers=_signed(body, ts=time.time() - 3600)).status_code == 401  # stale
    assert handled == ["<r1@supplier.example>"]


def test_verification_is_skipped_only_outside_production_with_no_secret(org_inbox, handled, monkeypatch):
    client, headers, org_id = org_inbox
    monkeypatch.setattr(settings, "agentmail_webhook_secret", "")
    body = json.dumps(_event()).encode()
    assert client.post("/api/webhooks/agentmail", content=body).status_code == 200
    monkeypatch.setattr(settings, "env", "production")
    r = client.post("/api/webhooks/agentmail", content=json.dumps(_event(mid="<r2@s>")).encode())
    assert r.status_code == 503
    assert handled == ["<r1@supplier.example>"]


# ------------------------------------------------------------------ routing
def test_other_event_types_and_bad_payloads(org_inbox, handled):
    client, headers, org_id = org_inbox
    sent = {"type": "event", "event_type": "message.sent", "event_id": "e", "send": {"inbox_id": INBOX}}
    assert client.post("/api/webhooks/agentmail", json=sent).status_code == 200
    assert client.post("/api/webhooks/agentmail", content=b"{not json").status_code == 400
    missing = _event()
    del missing["message"]["inbox_id"]
    assert client.post("/api/webhooks/agentmail", json=missing).status_code == 400
    assert handled == [] and _rows() == []


def test_unknown_inbox_is_dropped_with_200(org_inbox, handled, caplog):
    client, headers, org_id = org_inbox
    with caplog.at_level("WARNING", logger="procureai.webhooks.agentmail"):
        r = client.post("/api/webhooks/agentmail", json=_event(inbox="nobody@proq.tryproq.dev"))
    assert r.status_code == 200 and r.text == "unknown inbox"
    assert "unknown inbox" in caplog.text
    assert handled == [] and _rows() == []


def test_delivery_is_idempotent_on_the_message_id(org_inbox, handled):
    client, headers, org_id = org_inbox
    for _ in range(3):
        assert client.post("/api/webhooks/agentmail", json=_event()).status_code == 200
    assert len(_rows()) == 1 and handled == ["<r1@supplier.example>"]


# --------------------------------------------------------------- the row
def test_row_fields_and_attachments_are_stored(org_inbox, handled, monkeypatch):
    client, headers, org_id = org_inbox
    fake = FakeAgentMail(attachments={"att_1": b"%PDF-1.4 quote", "att_missing": None})
    monkeypatch.setattr(agentmail_client, "get_client", lambda: fake)
    monkeypatch.setattr(webhooks_agentmail, "_download",
                        lambda client, inbox_id, message_id, att_id: fake._attachments.get(att_id))
    event = _event(attachments=[
        {"attachment_id": "att_1", "filename": "../Quote Rev 2.pdf", "content_type": "application/pdf", "size": 14},
        {"attachment_id": "att_missing", "filename": "gone.pdf", "content_type": "application/pdf", "size": 1},
    ])
    assert client.post("/api/webhooks/agentmail", json=event).status_code == 200
    [row] = _rows()
    assert row.organization_id == org_id
    assert row.provider_message_id == "<r1@supplier.example>"
    assert row.inbox_id == INBOX and row.thread_id == "thr_1"
    assert row.in_reply_to == "<m1@agentmail.to>" and row.references == "<m1@agentmail.to>"
    assert row.rfc_message_id == "<r1@supplier.example>"
    assert row.from_email == "sales@pipe.co" and row.from_name == "Sales Team"
    assert json.loads(row.to_addresses) == [f"Proq for Acme <{INBOX}>"]
    assert json.loads(row.cc_addresses) == ["pm@own.com"]
    assert row.subject == "Re: RFQ: Water"
    assert row.text == "Quote $52,000 total"  # extracted_text wins over text
    assert row.html == "<p>Quote $52,000 total</p>"
    assert row.kind == "unknown" and row.processed_at is None
    [att] = json.loads(row.attachments)
    assert att["filename"] == "../Quote Rev 2.pdf" and att["mimeType"] == "application/pdf"
    assert att["size"] == 14 and att["locator"].endswith("Quote_Rev_2.pdf")
    assert ".." not in att["locator"].split("/")[-1]
    with open(att["locator"], "rb") as fh:
        assert fh.read() == b"%PDF-1.4 quote"
    # The failed download was skipped, not fatal.
    assert handled == ["<r1@supplier.example>"]
    # Visible to the org through the authed listing, and to nobody else.
    listed = client.get("/api/inbound?kind=unknown", headers=headers).json()
    assert [x["providerMessageId"] for x in listed] == ["<r1@supplier.example>"]
    assert listed[0]["attachments"][0]["filename"] == "../Quote Rev 2.pdf"
    other = client.post("/api/auth/register", json={"email": "o@other.com", "password": "password123"}).json()
    other_headers = {"Authorization": f"Bearer {other['accessToken']}"}
    assert client.get("/api/inbound", headers=other_headers).json() == []
    assert client.post(f"/api/inbound/{row.id}/reprocess", headers=other_headers).status_code == 404


def test_text_falls_back_to_the_plain_body_when_nothing_was_extracted(org_inbox, handled):
    client, headers, org_id = org_inbox
    event = _event(extracted_text=None, text="Plain body only")
    assert client.post("/api/webhooks/agentmail", json=event).status_code == 200
    assert _rows()[0].text == "Plain body only"


# -------------------------------------------------------------- handler
def test_a_handler_failure_never_fails_the_delivery_and_lands_on_the_row(org_inbox, monkeypatch):
    client, headers, org_id = org_inbox

    def boom(db, row):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(inbound, "handle", boom)
    assert client.post("/api/webhooks/agentmail", json=_event()).status_code == 200
    [row] = _rows()
    assert row.error == "parser exploded" and row.attempts == 1 and row.processed_at is None
    # Reprocess re-runs the handler; with it fixed the row is clean again.
    monkeypatch.setattr(inbound, "handle", lambda db, r: None)
    r = client.post(f"/api/inbound/{row.id}/reprocess", headers=headers)
    assert r.status_code == 200 and r.json()["error"] is None and r.json()["kind"] == "unknown"


def test_unattributed_mail_stays_unknown_after_the_real_dispatcher(org_inbox, monkeypatch):
    """The real dispatcher: no RFQ thread matches and the sender is not a
    user, so the row is left for a human (intake is another stream's stub)."""
    client, headers, org_id = org_inbox
    from app.services.inbound import intake

    monkeypatch.setattr(intake, "attribute", lambda db, row: False)
    assert client.post("/api/webhooks/agentmail", json=_event()).status_code == 200
    [row] = _rows()
    assert row.kind == "unknown" and row.processed_at is None and row.error is None
    assert client.get("/api/inbound?kind=unknown", headers=headers).json()[0]["id"] == row.id
