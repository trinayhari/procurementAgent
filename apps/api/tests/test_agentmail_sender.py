"""AgentMailSender + the per-organization agent inbox.

The SDK client is replaced by tests.agentmail_fakes.FakeAgentMail through the
module-level factory `agentmail_client.get_client`; the API key is blank in
conftest so nothing here can reach AgentMail.
"""
import base64
import time

import pytest

from app.config import settings
from app.db import SessionLocal
from app.models.organization import Organization
from app.repositories import organizations as organizations_repo
from app.services.email import agentmail_client
from app.services.rfq import sender as rfq_sender
from tests.agentmail_fakes import ApiError, FakeAgentMail
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search


@pytest.fixture()
def fake(monkeypatch):
    client = FakeAgentMail()
    monkeypatch.setattr(agentmail_client, "get_client", lambda: client)
    monkeypatch.setattr(rfq_sender.time, "sleep", lambda *_: None)
    return client


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(settings, "agentmail_api_key", "am_test_key")
    monkeypatch.setattr(settings, "agentmail_domain", "")
    monkeypatch.setattr(settings, "agentmail_pod_id", "")
    monkeypatch.setattr(settings, "agentmail_display_name_prefix", "Proq for")
    yield
    rfq_sender.reset_state()


def _org(client, headers):
    org_id = client.get("/api/auth/me", headers=headers).json()["organizationId"]
    db = SessionLocal()
    try:
        return db.get(Organization, org_id).name, org_id
    finally:
        db.close()


# ------------------------------------------------------------------ inboxes
def test_inbox_is_created_once_per_org_and_stored(auth, fake, configured):
    client, headers = auth
    db = SessionLocal()
    try:
        org = organizations_repo.create_organization(db, "Acme Construction, LLC")
        first = agentmail_client.ensure_inbox(db, org)
        second = agentmail_client.ensure_inbox(db, org)
        assert first == second == "acme-construction-llc@agentmail.to"
        db.refresh(org)
        assert org.agentmail_inbox_id == first
        assert agentmail_client.inbox_address(db, org.id) == first
        assert agentmail_client.org_for_inbox(db, first).id == org.id
        assert agentmail_client.org_for_inbox(db, "nobody@agentmail.to") is None
    finally:
        db.close()
    assert len(fake.created) == 1
    created = fake.created[0]
    assert created["display_name"] == "Proq for Acme Construction, LLC"
    assert created["client_id"] == created["metadata"]["organization_id"]
    assert "domain" not in created  # AgentMail's default domain when unset


def test_inbox_uses_the_custom_domain_and_pod_when_set(auth, fake, configured, monkeypatch):
    monkeypatch.setattr(settings, "agentmail_domain", "proq.tryproq.dev")
    monkeypatch.setattr(settings, "agentmail_pod_id", "pod_123")
    db = SessionLocal()
    try:
        org = organizations_repo.create_organization(db, "Meridian Civil")
        assert agentmail_client.ensure_inbox(db, org) == "meridian-civil@proq.tryproq.dev"
    finally:
        db.close()
    assert fake.created[0]["pod_id"] == "pod_123" and fake.created[0]["domain"] == "proq.tryproq.dev"


def test_inbox_username_gets_a_suffix_when_taken(auth, configured, monkeypatch):
    client = FakeAgentMail(taken={"acme@agentmail.to"})
    monkeypatch.setattr(agentmail_client, "get_client", lambda: client)
    db = SessionLocal()
    try:
        org = organizations_repo.create_organization(db, "Acme")
        inbox = agentmail_client.ensure_inbox(db, org)
    finally:
        db.close()
    assert inbox.startswith("acme-") and inbox.endswith("@agentmail.to") and inbox != "acme@agentmail.to"
    assert [c["username"] for c in client.created][0] == "acme"
    assert len(client.created) == 2


def test_get_sender_resolves_the_orgs_inbox_or_falls_back_to_mock(auth, fake, configured, monkeypatch):
    client, headers = auth
    _, org_id = _org(client, headers)
    db = SessionLocal()
    try:
        sender = rfq_sender.get_sender(db, org_id)
        assert isinstance(sender, rfq_sender.AgentMailSender)
        assert sender.address == rfq_sender.sender_address(db, org_id)
        assert sender.address.endswith("@agentmail.to")
        monkeypatch.setattr(settings, "agentmail_api_key", "")
        assert isinstance(rfq_sender.get_sender(db, org_id), rfq_sender.MockSender)
        assert rfq_sender.get_sender(db, org_id).address == rfq_sender.UNCONFIGURED_SENDER_ADDRESS
    finally:
        db.close()


def test_get_sender_reports_an_inbox_creation_failure_readably(auth, configured, monkeypatch):
    client, headers = auth
    _, org_id = _org(client, headers)
    dead = FakeAgentMail()
    monkeypatch.setattr(agentmail_client, "get_client", lambda: dead)
    monkeypatch.setattr(dead.inboxes, "create", lambda **kw: (_ for _ in ()).throw(ApiError(401, "Unauthorized")))
    db = SessionLocal()
    try:
        with pytest.raises(rfq_sender.EmailUnavailable, match="HTTP 401"):
            rfq_sender.get_sender(db, org_id)
    finally:
        db.close()
    assert "HTTP 401" in rfq_sender.provider_status()["lastError"]


# ------------------------------------------------------------------- sending
def test_send_starts_a_thread_and_reply_stays_in_it(fake):
    s = rfq_sender.AgentMailSender("acme@agentmail.to")
    out = s.send("sup@x.com", "RFQ: Water", "please quote", from_addr="acme@agentmail.to", cc="pm@own.com")
    assert (out.message_id, out.thread_id) == ("<m1@agentmail.to>", "thr_1")
    assert fake.sent == [{
        "inbox_id": "acme@agentmail.to", "in_reply_to": None, "to": ["sup@x.com"],
        "subject": "RFQ: Water", "text": "please quote", "cc": ["pm@own.com"],
    }]
    reply = s.send("sup@x.com", "Re: RFQ: Water", "you won", from_addr="acme@agentmail.to",
                   thread_id=out.thread_id, in_reply_to=out.message_id)
    assert fake.replied == [{
        "inbox_id": "acme@agentmail.to", "in_reply_to": "<m1@agentmail.to>", "to": ["sup@x.com"],
        "text": "you won",
    }]
    assert reply.thread_id == "thr_of_<m1@agentmail.to>"
    # A mock/error id from an older send is not a message we can reply to.
    s.send("sup@x.com", "Re: RFQ", "hi", from_addr="acme@agentmail.to", in_reply_to="mock-abc")
    assert len(fake.sent) == 2 and len(fake.replied) == 1


def test_cc_is_dropped_when_it_duplicates_the_recipient_or_the_inbox(fake):
    s = rfq_sender.AgentMailSender("acme@agentmail.to")
    s.send("sup@x.com", "s", "b", from_addr="acme@agentmail.to", cc="SUP@x.com")
    s.send("sup@x.com", "s", "b", from_addr="acme@agentmail.to", cc="acme@agentmail.to")
    s.send("sup@x.com", "s", "b", from_addr="acme@agentmail.to", cc="pm@own.com", reply_to="pm@own.com")
    assert "cc" not in fake.sent[0] and "cc" not in fake.sent[1]
    assert fake.sent[2]["cc"] == ["pm@own.com"] and fake.sent[2]["reply_to"] == "pm@own.com"


def test_attachments_are_base64_payloads_with_types(fake):
    s = rfq_sender.AgentMailSender("acme@agentmail.to")
    s.send("sup@x.com", "s", "b", from_addr="acme@agentmail.to", attachments=[
        rfq_sender.EmailAttachment("Plans Rev 2.pdf", b"%PDF-1.4 fake"),
        rfq_sender.EmailAttachment("weird.bin", b"\x00\x01"),
    ])
    parts = fake.sent[0]["attachments"]
    assert [(p["filename"], p["content_type"]) for p in parts] == [
        ("Plans Rev 2.pdf", "application/pdf"), ("weird.bin", "application/octet-stream"),
    ]
    assert base64.b64decode(parts[0]["content"]) == b"%PDF-1.4 fake"


def test_send_refuses_blank_or_oversized_mail_before_calling_the_api(fake):
    s = rfq_sender.AgentMailSender("acme@agentmail.to")
    with pytest.raises(rfq_sender.EmailUnavailable, match="body is empty"):
        s.send("a@x.com", "s", "   ", from_addr="acme@agentmail.to")
    with pytest.raises(rfq_sender.EmailUnavailable, match="subject is empty"):
        s.send("a@x.com", "", "hello", from_addr="acme@agentmail.to")
    with pytest.raises(rfq_sender.EmailUnavailable, match="recipient"):
        s.send("not-an-address", "s", "hello", from_addr="acme@agentmail.to")
    big = rfq_sender.EmailAttachment("plans.pdf", b"x" * (rfq_sender.MAX_ATTACHMENT_TOTAL_BYTES + 1))
    with pytest.raises(rfq_sender.EmailUnavailable, match="MB email limit"):
        s.send("a@x.com", "s", "hello", from_addr="acme@agentmail.to", attachments=[big])
    assert fake.sent == [] and fake.replied == []


# -------------------------------------------------------------------- errors
@pytest.mark.parametrize("exc, needle, retryable", [
    (ApiError(401, "Unauthorized"), "PROCUREAI_AGENTMAIL_API_KEY", False),
    (ApiError(429, "Too Many Requests"), "rate limiting", True),
    (ApiError(503, "Service Unavailable"), "temporarily unavailable (HTTP 503)", True),
    (ApiError(422, "Invalid recipient address", fix="Check the email"), "recipient address", False),
    (ApiError(413, "Request Entity Too Large"), "6 MB", False),
    (ConnectionError("Connection refused"), "network error", False),
])
def test_errors_are_described_for_humans(exc, needle, retryable):
    text = rfq_sender.describe_error(exc)
    assert needle in text
    assert "status_code" not in text and "headers:" not in text
    assert rfq_sender._retryable(exc) is retryable


def test_send_retries_rate_limit_then_succeeds(monkeypatch):
    from types import SimpleNamespace

    fake = FakeAgentMail(send_results=[ApiError(429, "slow down"),
                                       SimpleNamespace(message_id="<m9@am>", thread_id="t9")])
    monkeypatch.setattr(agentmail_client, "get_client", lambda: fake)
    monkeypatch.setattr(rfq_sender.time, "sleep", lambda *_: None)
    out = rfq_sender.AgentMailSender("acme@agentmail.to").send("sup@x.com", "RFQ", "body", from_addr="x")
    assert (out.message_id, out.thread_id) == ("<m9@am>", "t9")
    assert len(fake.sent) == 2
    assert rfq_sender.provider_status()["lastError"] is None
    rfq_sender.reset_state()


def test_send_gives_up_after_retries_with_a_readable_error(monkeypatch):
    fake = FakeAgentMail(send_results=[ApiError(503), ApiError(503), ApiError(503)])
    monkeypatch.setattr(agentmail_client, "get_client", lambda: fake)
    monkeypatch.setattr(rfq_sender.time, "sleep", lambda *_: None)
    with pytest.raises(rfq_sender.EmailUnavailable) as ei:
        rfq_sender.AgentMailSender("acme@agentmail.to").send("sup@x.com", "RFQ", "body", from_addr="x")
    assert "HTTP 503" in str(ei.value) and ei.value.retryable
    assert len(fake.sent) == 3
    assert "HTTP 503" in rfq_sender.provider_status()["lastError"]
    rfq_sender.reset_state()


def test_send_does_not_retry_permanent_errors(monkeypatch):
    fake = FakeAgentMail(send_results=[ApiError(422, "Invalid recipient address")])
    monkeypatch.setattr(agentmail_client, "get_client", lambda: fake)
    with pytest.raises(rfq_sender.EmailUnavailable) as ei:
        rfq_sender.AgentMailSender("acme@agentmail.to").send("sup@x.com", "RFQ", "body", from_addr="x")
    assert len(fake.sent) == 1 and not ei.value.retryable
    rfq_sender.reset_state()


# ------------------------------------------------------------ end to end
def test_rfq_send_creates_the_inbox_and_records_agentmail_ids(project, fake, configured):
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:2])
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "Awaiting"
    for rcp, sent in zip(r.json()["recipients"], fake.sent):
        assert rcp["messageId"] == rcp["sentMessageId"] and rcp["messageId"].startswith("<m")
        assert rcp["threadId"].startswith("thr_") and rcp["sentAt"] and rcp["mock"] is False
        assert sent["to"] == [rcp["email"]]
    assert len(fake.created) == 1  # one inbox for the org, reused for both sends
    cfg = client.get("/api/auth/email-config", headers=headers).json()
    assert cfg["configured"] is True and cfg["inboxAddress"] == fake.created[0]["inbox_id"]
    assert cfg["fromHeader"] == f"PM <{cfg['inboxAddress']}>"


def test_test_email_goes_from_the_org_inbox_to_the_user(auth, fake, configured):
    client, headers = auth
    r = client.post("/api/auth/test-email", headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mocked"] is False and out["to"] == "pm@example.com"
    assert out["fromAddr"] == f"PM <{fake.created[0]['inbox_id']}>"
    assert fake.sent[0]["inbox_id"] == fake.created[0]["inbox_id"]
    assert fake.sent[0]["to"] == ["pm@example.com"]
    # The health probe reads the inbox back through the API.
    body = client.get("/api/health/providers", headers=headers).json()
    assert body["email"]["ok"] is True and body["email"]["inboxAddress"] == fake.created[0]["inbox_id"]


# ------------------------------------------------------------ Svix signing
def _signed_headers(secret, body, msg_id="msg_1", ts=None):
    ts = str(int(ts if ts is not None else time.time()))
    return {
        "svix-id": msg_id,
        "svix-timestamp": ts,
        "svix-signature": agentmail_client.sign_payload(secret, msg_id, ts, body),
    }


def test_verify_svix_accepts_a_valid_signature_and_rejects_the_rest():
    secret = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
    body = b'{"event_type":"message.received"}'
    good = _signed_headers(secret, body)
    assert agentmail_client.verify_svix(secret, good, body)
    # Case-insensitive header names, several signatures in the header.
    upper = {k.upper(): v for k, v in good.items()}
    upper["SVIX-SIGNATURE"] = "v1,bogus " + good["svix-signature"]
    assert agentmail_client.verify_svix(secret, upper, body)
    assert not agentmail_client.verify_svix(secret, good, body + b" ")  # tampered body
    assert not agentmail_client.verify_svix("whsec_" + base64.b64encode(b"other").decode(), good, body)
    assert not agentmail_client.verify_svix(secret, {}, body)  # headers missing
    stale = _signed_headers(secret, body, ts=time.time() - 3600)
    assert not agentmail_client.verify_svix(secret, stale, body)  # too old
    assert not agentmail_client.verify_svix("", good, body)  # no secret
