"""Email workflow robustness: send errors, MIME, Gmail reading, ingest
idempotency / supersede / needs-review, conversation fallback honesty, award
notifications and config truthfulness.

Provider creds are force-blanked in conftest, so every Gmail call here goes
through a fake service or a recording sender — nothing can reach the network.
"""
import base64
import json
from email import message_from_bytes
from email.header import decode_header, make_header
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.quotes import gmail_reader, ingest, pdf_text
from app.services.quotes.models import ParsedQuote, ParsedQuoteLine
from app.services.rfq import award_notify
from app.services.rfq import conversation as rfq_conversation
from app.services.rfq import sender as rfq_sender
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search


# ---------------------------------------------------------------- helpers
class _HttpError(Exception):
    """Shape of googleapiclient.errors.HttpError (has .resp.status)."""

    def __init__(self, status, reason="boom"):
        super().__init__(f"<HttpError {status} when requesting x returned \"{reason}\">")
        self.resp = SimpleNamespace(status=status)


class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _FakeGmail:
    """Enough of the googleapiclient surface for messages.send / list / get / threads.get."""

    def __init__(self, *, send_results=None, messages=None, thread=None):
        self.send_results = list(send_results or [])
        self.sent_bodies = []
        self.messages = messages or {}
        self.thread = thread or {"messages": []}
        self.list_ids = list(self.messages.keys())

    # --- send
    def _send(self, body):
        self.sent_bodies.append(body)
        result = self.send_results.pop(0) if self.send_results else {"id": "sent-1", "threadId": "thr-1"}
        if isinstance(result, Exception):
            raise result
        return result

    def users(self):
        svc = self

        class Messages:
            def send(self, userId, body):
                return _Exec(lambda: svc._send(body))

            def list(self, userId, q, maxResults):
                return _Exec(lambda: {"messages": [{"id": i} for i in svc.list_ids]})

            def get(self, userId, id, format="full", metadataHeaders=None):
                return _Exec(lambda: svc.messages[id])

            def attachments(self):
                raise AssertionError("no attachments in these fixtures")

        class Threads:
            def get(self, userId, id, format="full"):
                return _Exec(lambda: svc.thread)

        class Users:
            def messages(self):
                return Messages()

            def threads(self):
                return Threads()

        return Users()


def _gmail_sender(monkeypatch, fake, refresh_error=None):
    """A GmailSender whose _service() returns `fake` (or raises)."""
    s = rfq_sender.GmailSender()
    calls = {"n": 0}

    def _service():
        calls["n"] += 1
        if refresh_error is not None:
            raise rfq_sender.GmailUnavailable(
                rfq_sender.describe_gmail_error(refresh_error, stage="token refresh")
            )
        return fake

    monkeypatch.setattr(s, "_service", _service)
    monkeypatch.setattr(rfq_sender.time, "sleep", lambda *_: None)
    return s, calls


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _msg(mid, frm, subject, text=None, html=None, thread="thr", date_ms=1000, labels=None):
    parts = []
    if text is not None:
        parts.append({"mimeType": "text/plain", "body": {"data": _b64(text)}})
    if html is not None:
        parts.append({"mimeType": "text/html", "body": {"data": _b64(html)}})
    payload = {
        "mimeType": "multipart/alternative",
        "headers": [{"name": "From", "value": frm}, {"name": "Subject", "value": subject}],
        "parts": parts,
    }
    return {
        "id": mid, "threadId": thread, "internalDate": str(date_ms),
        "snippet": (text or html or "")[:40], "payload": payload,
        "labelIds": labels or ["INBOX"],
    }


# ============================================================== sender errors
@pytest.mark.parametrize("raw, needle", [
    ("('invalid_grant: Token has been expired or revoked.', {'error': 'invalid_grant'})", "invalid_grant"),
    ("('invalid_client: The OAuth client was not found.', {})", "PROCUREAI_GMAIL_CLIENT_ID"),
    (_HttpError(429, "User-rate limit exceeded"), "rate limiting"),
    (_HttpError(503, "Backend Error"), "temporarily unavailable (HTTP 503)"),
    (_HttpError(400, "Invalid to header"), "recipient address"),
])
def test_gmail_errors_are_described_for_humans(raw, needle):
    exc = raw if isinstance(raw, Exception) else Exception(raw)
    text = rfq_sender.describe_gmail_error(exc)
    assert needle in text
    assert "{'error'" not in text  # no raw dict dumps


def test_gmail_send_retries_rate_limit_then_succeeds(monkeypatch):
    fake = _FakeGmail(send_results=[_HttpError(429, "rateLimitExceeded"), {"id": "m9", "threadId": "t9"}])
    s, _ = _gmail_sender(monkeypatch, fake)
    out = s.send("sup@x.com", "RFQ", "body", from_addr="bids@ws.com")
    assert (out.message_id, out.thread_id) == ("m9", "t9")
    assert len(fake.sent_bodies) == 2


def test_gmail_send_gives_up_after_retries_with_readable_error(monkeypatch):
    fake = _FakeGmail(send_results=[_HttpError(503), _HttpError(503), _HttpError(503)])
    s, _ = _gmail_sender(monkeypatch, fake)
    with pytest.raises(rfq_sender.GmailUnavailable) as ei:
        s.send("sup@x.com", "RFQ", "body", from_addr="bids@ws.com")
    assert "HTTP 503" in str(ei.value) and ei.value.retryable


def test_gmail_send_does_not_retry_permanent_errors(monkeypatch):
    fake = _FakeGmail(send_results=[_HttpError(400, "Invalid to header")])
    s, _ = _gmail_sender(monkeypatch, fake)
    with pytest.raises(rfq_sender.GmailUnavailable) as ei:
        s.send("sup@x.com", "RFQ", "body", from_addr="bids@ws.com")
    assert len(fake.sent_bodies) == 1
    assert not ei.value.retryable


def test_gmail_sender_refreshes_the_token_once_per_batch(monkeypatch):
    fake = _FakeGmail(send_results=[{"id": "a", "threadId": "a"}, {"id": "b", "threadId": "b"}])
    s = rfq_sender.GmailSender()
    builds = {"n": 0}
    real = s._service

    def _service():
        if s._svc is None:
            builds["n"] += 1
            s._svc = fake
        return real()

    monkeypatch.setattr(s, "_service", _service)
    s.send("a@x.com", "s", "b", from_addr="bids@ws.com")
    s.send("b@x.com", "s", "b", from_addr="bids@ws.com")
    assert builds["n"] == 1


def test_gmail_send_refuses_blank_or_oversized_mail_before_calling_gmail(monkeypatch):
    fake = _FakeGmail()
    s, calls = _gmail_sender(monkeypatch, fake)
    with pytest.raises(rfq_sender.GmailUnavailable, match="body is empty"):
        s.send("a@x.com", "s", "   ", from_addr="bids@ws.com")
    with pytest.raises(rfq_sender.GmailUnavailable, match="subject is empty"):
        s.send("a@x.com", "", "hello", from_addr="bids@ws.com")
    with pytest.raises(rfq_sender.GmailUnavailable, match="recipient"):
        s.send("not-an-address", "s", "hello", from_addr="bids@ws.com")
    big = rfq_sender.EmailAttachment("plans.pdf", b"x" * (rfq_sender.MAX_ATTACHMENT_TOTAL_BYTES + 1))
    with pytest.raises(rfq_sender.GmailUnavailable, match="MB email limit"):
        s.send("a@x.com", "s", "hello", from_addr="bids@ws.com", attachments=[big])
    assert calls["n"] == 0 and fake.sent_bodies == []


# ================================================================ MIME shape
def _decode(raw):
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def test_mime_carries_utf8_subject_body_and_attachment_types():
    att_pdf = rfq_sender.EmailAttachment("Plans — Rev 2.pdf", b"%PDF-1.4 fake")
    att_bin = rfq_sender.EmailAttachment("weird.bin", b"\x00\x01")
    raw = rfq_sender._build_mime(
        "Sales <sales@pipe.co>", "RFQ: Tubería — Río Project", "Hola — 12″ pipe ½ price\nGracias",
        rfq_sender.from_header(SimpleNamespace(name="José Núñez", company="Acme — Civil")),
        attachments=[att_pdf, att_bin],
    )
    msg = _decode(raw)
    assert str(make_header(decode_header(msg["Subject"]))) == "RFQ: Tubería — Río Project"
    assert "José Núñez — Acme — Civil" in str(make_header(decode_header(msg["From"])))
    parts = list(msg.walk())
    text = next(p for p in parts if p.get_content_type() == "text/plain")
    assert "12″ pipe ½" in text.get_payload(decode=True).decode("utf-8")
    types = {p.get_filename(): p.get_content_type() for p in parts if p.get_filename()}
    assert types == {"Plans — Rev 2.pdf": "application/pdf", "weird.bin": "application/octet-stream"}
    assert msg["Reply-To"] is None


def test_mime_headers_cannot_be_injected():
    raw = rfq_sender._build_mime(
        "sales@pipe.co\r\nBcc: victim@x.com",
        "RFQ\nX-Injected: yes",
        "body",
        "bids@ws.com",
        cc="pm@own.com\r\nTo: other@x.com",
        attachments=[rfq_sender.EmailAttachment("a.pdf\r\nX-Evil: 1", b"x")],
    )
    msg = _decode(raw)
    assert msg["Bcc"] is None and msg["X-Injected"] is None and msg["X-Evil"] is None
    assert msg.get_all("To") == ["sales@pipe.coBcc: victim@x.com"]
    assert msg["Subject"] == "RFQX-Injected: yes"


# ============================================================== configuration
@pytest.mark.parametrize("cid, secret, token, addr, configured, missing", [
    ("id", "sec", "tok", "bids@ws.com", True, []),
    ("id", "sec", "tok", "", False, ["PROCUREAI_GMAIL_SENDER_ADDRESS"]),
    ("", "", "", "bids@ws.com", False, [
        "PROCUREAI_GMAIL_CLIENT_ID", "PROCUREAI_GMAIL_CLIENT_SECRET", "PROCUREAI_GMAIL_REFRESH_TOKEN"]),
    ("id", "sec", "", "bids@ws.com", False, ["PROCUREAI_GMAIL_REFRESH_TOKEN"]),
    ("", "", "", "", False, [
        "PROCUREAI_GMAIL_CLIENT_ID", "PROCUREAI_GMAIL_CLIENT_SECRET",
        "PROCUREAI_GMAIL_REFRESH_TOKEN", "PROCUREAI_GMAIL_SENDER_ADDRESS"]),
])
def test_email_config_is_truthful_for_every_combination(monkeypatch, cid, secret, token, addr, configured, missing):
    monkeypatch.setattr(settings, "gmail_client_id", cid)
    monkeypatch.setattr(settings, "gmail_client_secret", secret)
    monkeypatch.setattr(settings, "gmail_refresh_token", token)
    monkeypatch.setattr(settings, "gmail_sender_address", addr)
    cfg = rfq_sender.email_config()
    assert cfg["configured"] is configured and cfg["mocked"] is (not configured)
    assert cfg["missing"] == missing
    assert cfg["senderAddressSet"] is bool(addr)
    # Anything short of fully configured never produces a real Gmail sender.
    assert isinstance(rfq_sender.get_sender(), rfq_sender.MockSender) is (not configured)


def test_email_config_endpoint_lists_missing_vars(auth):
    client, headers = auth
    cfg = client.get("/api/auth/email-config", headers=headers).json()
    assert cfg["configured"] is False
    assert "PROCUREAI_GMAIL_REFRESH_TOKEN" in cfg["missing"]


# ============================================================ send route
def _rfq_ready(client, headers, pid, n=2):
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    return bom_id, generate_rfq(client, headers, pid, bom_id, sids[:n])


def test_expired_token_marks_every_recipient_failed_with_a_readable_reason(project, monkeypatch):
    client, headers, pid = project
    _, rfq = _rfq_ready(client, headers, pid)

    class Dead:
        mocked = False

        def send(self, *a, **kw):
            raise rfq_sender.GmailUnavailable(rfq_sender.describe_gmail_error(
                Exception("('invalid_grant: Token has been expired or revoked.', {})")))

    monkeypatch.setattr(rfq_sender, "get_sender", lambda: Dead())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "Send failed"
    for rec in body["recipients"]:
        assert rec["sendStatus"] == "failed"
        assert "invalid_grant" in rec["sendError"] and "re-mint" in rec["sendError"]
        assert "{'error'" not in rec["sendError"]
    # Not stuck: a retry with a working sender delivers to everyone.
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: rfq_sender.MockSender())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "Awaiting"
    assert all(rec["sendStatus"] == "sent" and rec["threadId"] for rec in r.json()["recipients"])


def test_blank_subject_or_body_cannot_be_sent(project):
    client, headers, pid = project
    _, rfq = _rfq_ready(client, headers, pid)
    r = client.put(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers,
                   json={"subject": rfq["subject"], "body": "   ", "recipients": rfq["recipients"]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 400 and "body is empty" in r.json()["detail"]
    assert client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()["status"] == "Draft"


def test_send_progress_is_persisted_per_recipient(project, monkeypatch):
    """A crash after the first supplier used to leave the RFQ a Draft with no
    record of that send — a retry would email them again. The recipient
    record is now written after every attempt."""
    import copy

    from app.api.routes import sourcing as sourcing_routes

    client, headers, pid = project
    _, rfq = _rfq_ready(client, headers, pid, n=2)
    mock = rfq_sender.MockSender()
    snapshots = []
    real_save = sourcing_routes.rfqs_repo.save_recipients

    def spy(db, org_id, rfq_id, recipients):
        snapshots.append(copy.deepcopy(recipients))
        real_save(db, org_id, rfq_id, recipients)

    monkeypatch.setattr(sourcing_routes.rfqs_repo, "save_recipients", spy)

    class FailSecond:
        mocked = True

        def send(self, to, subject, body, **kw):
            if len(snapshots) == 1:
                raise RuntimeError("boom")
            return mock.send(to, subject, body, **kw)

    monkeypatch.setattr(rfq_sender, "get_sender", lambda: FailSecond())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "Send failed"
    assert [[x.get("sendStatus") for x in snap] for snap in snapshots] == [["sent", None], ["sent", "failed"]]


# ============================================================ gmail reader
def test_fetch_replies_matches_the_exact_address_only(monkeypatch):
    fake = _FakeGmail(messages={
        "m1": _msg("m1", "Sales <sales@pipe.co>", "Re: RFQ", "Quote $1,000", date_ms=2000),
        "m2": _msg("m2", "Sales <sales@pipe.co.uk>", "Re: RFQ", "Quote $9,000", date_ms=1000),
        "m3": _msg("m3", "sales@pipe.com", "Re: RFQ", "Quote $8,000", date_ms=3000),
    })
    monkeypatch.setattr(gmail_reader, "_service", lambda: fake)
    out = gmail_reader.fetch_replies(["Sales@Pipe.co"])
    assert [m.message_id for m in out] == ["m1"]
    assert out[0].date_ms == 2000 and out[0].label_ids == ["INBOX"]


def test_fetch_replies_returns_oldest_first_and_reads_html_only_bodies(monkeypatch):
    fake = _FakeGmail(messages={
        "new": _msg("new", "s@x.com", "Re: RFQ", html="<div>Revised: <b>$47,500</b><br>10 days</div>"
                    "<blockquote>On … wrote: $52,000</blockquote>", date_ms=5000),
        "old": _msg("old", "s@x.com", "Re: RFQ", "Quote $52,000", date_ms=1000),
    })
    monkeypatch.setattr(gmail_reader, "_service", lambda: fake)
    out = gmail_reader.fetch_replies(["s@x.com"])
    assert [m.message_id for m in out] == ["old", "new"]
    assert out[1].text == "Revised: $47,500\n10 days"


@pytest.mark.parametrize("body, expected", [
    ("New: $10\n\nOn Tue, Sep 16, 2026 at 3:00 PM Jane Doe — Acme <bids@ws.com>\nwrote:\n> old $20", "New: $10"),
    ("New: $10\nOn Sep 16, 2026, at 3:00 PM, Jane <a@b.com> wrote:\n\n> old", "New: $10"),
    ("New: $10\n\nFrom: Jane Doe <a@b.com>\nSent: Tuesday, September 16, 2026 3:00 PM\nTo: x\nSubject: RFQ\n\nold $20", "New: $10"),
    ("New: $10\n\n________________________________\nFrom: a\nSent: b", "New: $10"),
    ("New: $10\n-----Original Message-----\nFrom: a", "New: $10"),
    ("New: $10\n\n**From:** Jane\n**Sent:** Tuesday\n\nold", "New: $10"),
    ("New: $10\n> old $20\n> more", "New: $10"),
    ("On hold until Friday.\nFrom our yard: $10", "On hold until Friday.\nFrom our yard: $10"),
    ("Le mar. 16 sept. 2026 à 15:00, Jane <a@b.com> a écrit :\n> old", ""),
])
def test_strip_quoted_covers_gmail_outlook_and_apple_mail(body, expected):
    assert gmail_reader._strip_quoted(body) == expected


def test_readers_skip_known_ids_before_downloading(monkeypatch):
    fake = _FakeGmail(messages={
        "known": _msg("known", "s@x.com", "Re: RFQ", "old $1", date_ms=1),
        "fresh": _msg("fresh", "s@x.com", "Re: RFQ", "new $2", date_ms=2),
    }, thread={"messages": [_msg("known", "s@x.com", "Re", "old $1"), _msg("fresh", "s@x.com", "Re", "new $2")]})
    gets = []
    real_users = fake.users

    def users():
        u = real_users()
        m = u.messages()
        orig_get = m.get

        def get(userId, id, **kw):
            gets.append(id)
            return orig_get(userId, id, **kw)

        m.get = get
        u.messages = lambda: m
        return u

    monkeypatch.setattr(fake, "users", users)
    monkeypatch.setattr(gmail_reader, "_service", lambda: fake)
    assert [m.message_id for m in gmail_reader.fetch_replies(["s@x.com"], skip_ids={"known"})] == ["fresh"]
    assert gets == ["fresh"]
    assert [m.message_id for m in gmail_reader.fetch_thread_replies("thr", skip_ids={"known"})] == ["fresh"]


def test_thread_names_are_decoded_from_rfc2047(monkeypatch):
    fake = _FakeGmail(thread={"messages": [
        _msg("o", "=?utf-8?q?Jane_Doe_=E2=80=94_Acme?= <bids@ws.com>", "=?utf-8?q?RFQ:_Tuber=C3=ADa?=", "please quote", date_ms=1),
        _msg("r", "Sales <s@x.com>", "Re: RFQ", "$5", date_ms=2),
    ]})
    monkeypatch.setattr(gmail_reader, "_service", lambda: fake)
    out = gmail_reader.fetch_thread("thr")
    assert out[0].from_name == "Jane Doe — Acme" and out[0].from_email == "bids@ws.com"
    assert out[0].subject == "RFQ: Tubería"


def test_pdf_text_survives_garbage_and_reads_a_real_pdf():
    assert pdf_text.extract(b"not a pdf at all") == ""
    assert pdf_text.extract(b"") == ""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Grand total $12,345.00")
    data = doc.tobytes()
    assert "12,345.00" in pdf_text.extract(data)


# ================================================================== ingest
def _live_gmail(monkeypatch, replies, parsed_by_text, threads=None):
    """Route ingest down the live path with canned replies and a canned parser.

    `replies` answer the from: search; `threads` ({thread_id: [messages]})
    answer the per-RFQ thread reads."""
    monkeypatch.setattr(ingest, "gmail_configured", lambda: True)
    monkeypatch.setattr(ingest.gmail_reader, "fetch_replies", lambda emails, lookback_days=30, skip_ids=None: [
        m for m in replies if m.from_email in {e.lower() for e in emails}
    ])
    monkeypatch.setattr(ingest.gmail_reader, "fetch_thread_replies",
                        lambda thread_id, skip_ids=None: list((threads or {}).get(thread_id, [])))
    monkeypatch.setattr(ingest.parser, "parse_quote", lambda text: parsed_by_text(text))


def _inbound(mid, frm, text, thread="", date_ms=0, subject="Re: RFQ"):
    return gmail_reader.InboundMessage(
        message_id=mid, from_email=frm, subject=subject, text=text,
        thread_id=thread, date_ms=date_ms,
    )


def _priced(total, name="Pipe Co"):
    return ParsedQuote(is_quote=True, supplier_name=name, total=total, material_cost=total,
                       line_items=[ParsedQuoteLine(name="Fire hydrant", quantity="5 EA", unit_price=total / 5)])


def test_live_ingest_is_idempotent_supersedes_revisions_and_flags_unpriced(project, monkeypatch):
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=2)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200
    recipients = r.json()["recipients"]
    sup = recipients[0]["email"]
    thread = recipients[0]["threadId"]
    our_msg = recipients[0]["sentMessageId"]

    def parse(text):
        if "$" not in text:
            return ParsedQuote(is_quote=True, supplier_name="Pipe Co", notes="see attached")
        amount = float(text.split("$")[1].split()[0].replace(",", ""))
        return _priced(amount)

    replies = [
        _inbound(our_msg, sup, "please quote $1,000,000", thread, 1),  # our own RFQ (loop-back)
        _inbound("r1", sup, "Quote $52,000 total", thread, 2),
        _inbound("r2", "stranger@nowhere.com", "Quote $1 total", thread, 3),  # unknown sender
        _inbound("r3", sup, "Attached is our quote (see PDF)", thread, 4),  # nothing priced
        _inbound("r4", sup, "Revised quote $47,500 total", thread, 5),
    ]
    _live_gmail(monkeypatch, replies, parse)

    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["status"] == "done", st
    assert st["mocked"] is False
    assert (st["ingested"], st["needsReview"], st["superseded"]) == (2, 1, 2)

    rows = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    # Only the latest revision is listed (and it is the best); nothing from the
    # stranger, nothing parsed out of our own outbound.
    assert [row["total"] for row in rows] == ["$47,500"]
    assert rows[0]["status"] == "received"
    assert client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()["status"] == "Quoted"

    # Re-running ingests nothing new and creates no duplicates.
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert (st["ingested"], st["needsReview"], st["superseded"]) == (0, 0, 0)
    assert len(client.get(f"/api/projects/{pid}/quotes", headers=headers).json()) == 1

    # Comparison sees exactly one supplier with the revised figure.
    cmp = client.get(f"/api/projects/{pid}/packages/{bom_id}/line-comparison", headers=headers)
    assert cmp.status_code == 200, cmp.text
    sups = cmp.json()["suppliers"]
    assert len(sups) == 1 and sups[0]["total"] == 47500.0


def test_unpriced_reply_alone_is_needs_review_not_quoted(project, monkeypatch):
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=1)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    sup = r.json()["recipients"][0]["email"]
    thread = r.json()["recipients"][0]["threadId"]
    _live_gmail(monkeypatch, [_inbound("r1", sup, "Attached.", thread, 1)],
                lambda text: ParsedQuote(is_quote=True, supplier_name="Pipe Co"))
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert (st["ingested"], st["needsReview"]) == (0, 1)
    rows = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert len(rows) == 1 and rows[0]["status"] == "needs_review" and rows[0]["total"] == "—"
    assert rows[0]["best"] is False
    # Still awaiting a real quote; nothing comparable exists yet.
    assert client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()["status"] == "Awaiting"
    assert client.get(f"/api/projects/{pid}/packages/{bom_id}/line-comparison", headers=headers).status_code == 404


def test_reply_from_another_address_in_our_thread_is_ingested_and_award_threads_on_it(project, monkeypatch):
    """RFQ went to sales@; the estimator answered from her own mailbox inside
    the same Gmail thread. The from: search never saw her; the thread does."""
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=1)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    rcp = r.json()["recipients"][0]
    thread = "thr-live-1"
    # Pretend the send went through Gmail (mock ids start with "mock", which
    # the thread reader skips).
    from app.db import SessionLocal
    from app.repositories import rfqs as rfqs_repo
    me = client.get("/api/auth/me", headers=headers).json()
    db = SessionLocal()
    try:
        rcp["threadId"] = thread
        rcp["sentMessageId"] = "gm-out-1"
        rfqs_repo.save_recipients(db, me["organizationId"], rfq["id"], [rcp])
    finally:
        db.close()
    monkeypatch.setattr(settings, "gmail_sender_address", "bids@ws.com")
    threads = {thread: [
        _inbound("gm-out-1", "bids@ws.com", "please quote", thread, 1),
        _inbound("est-1", "jane.estimator@supplier.example", "Quote $61,000 total", thread, 2),
    ]}
    _live_gmail(monkeypatch, [], lambda text: _priced(61000.0, name="Supplier Inc"), threads=threads)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["status"] == "done" and st["ingested"] == 1, st
    rows = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert rows[0]["total"] == "$61,000"
    assert client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()["status"] == "Quoted"

    rec = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: rec)
    r = client.post(f"/api/projects/{pid}/packages/{bom_id}/award", headers=headers, json={"selections": {}})
    assert r.status_code == 200, r.text
    # The PO goes to the address that quoted, threaded on the RFQ we sent to sales@.
    assert rec.sent == [{"to": "jane.estimator@supplier.example", "subject": f"Re: {rfq['subject']}",
                         "thread_id": thread, "cc": None}]


def test_reply_in_a_different_known_thread_is_not_attributed():
    """A supplier on ONE RFQ here replied to another project's RFQ (thread
    known, different) — the single-RFQ fallback must not claim it."""
    meta = {"rfq_id": "rB", "thread_id": "threadB", "subject": "RFQ: Water — Project B"}
    msg = SimpleNamespace(thread_id="threadA", subject="Re: RFQ: Sewer — Project A", message_id="m", from_email="s@x.com")
    assert ingest._match_rfq([meta], msg) is None
    promo = SimpleNamespace(thread_id="threadZ", subject="Spring promo", message_id="m2", from_email="s@x.com")
    assert ingest._match_rfq([meta], promo) is None
    # Legacy send with no thread on record: the single-RFQ rule still applies.
    legacy = {"rfq_id": "rB", "thread_id": "", "subject": "RFQ: Water — Project B"}
    assert ingest._match_rfq([legacy], promo) is legacy


def test_ingest_ignores_recipients_who_never_received_the_rfq(project, monkeypatch):
    client, headers, pid = project
    _, rfq = _rfq_ready(client, headers, pid, n=2)
    fail_email = rfq["recipients"][1]["email"]
    mock = rfq_sender.MockSender()

    class Flaky:
        mocked = True

        def send(self, to, subject, body, **kw):
            if to == fail_email:
                raise RuntimeError("boom")
            return mock.send(to, subject, body, **kw)

    monkeypatch.setattr(rfq_sender, "get_sender", lambda: Flaky())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.json()["status"] == "Send failed"
    asked = {}

    def fetch(emails, lookback_days=30, skip_ids=None):
        asked["emails"] = sorted(emails)
        return []

    monkeypatch.setattr(ingest, "gmail_configured", lambda: True)
    monkeypatch.setattr(ingest.gmail_reader, "fetch_replies", fetch)
    monkeypatch.setattr(ingest.gmail_reader, "fetch_thread_replies", lambda t, skip_ids=None: [])
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    assert asked["emails"] == [rfq["recipients"][0]["email"]]


def test_unit_priced_reply_is_totalled_with_the_rfq_quantities(project, monkeypatch):
    """Regex path (no model configured): 'hydrant $3,150 each, valve $1,240
    each, freight $900' against an RFQ asking for 5 hydrants and 9 valves."""
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=1)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    rcp = r.json()["recipients"][0]
    reply = _inbound("u1", rcp["email"], "Fire hydrant $3,150.00 each, 8-inch gate valve $1,240 each, freight $900, 4 weeks",
                     rcp["threadId"], 1)
    monkeypatch.setattr(ingest, "gmail_configured", lambda: True)
    monkeypatch.setattr(ingest.gmail_reader, "fetch_replies", lambda emails, lookback_days=30, skip_ids=None: [reply])
    monkeypatch.setattr(ingest.gmail_reader, "fetch_thread_replies", lambda t, skip_ids=None: [])
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["ingested"] == 1, st
    q = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()[0]
    assert (q["amount"], q["freight"], q["total"], q["lead"]) == ("$26,910", "$900", "$27,810", "28 days")


def test_ingest_honours_the_lookback_setting(monkeypatch, project):
    client, headers, pid = project
    _, rfq = _rfq_ready(client, headers, pid, n=1)
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    seen = {}

    def fetch(emails, lookback_days=30, skip_ids=None):
        seen["lookback"] = lookback_days
        return []

    monkeypatch.setattr(ingest, "gmail_configured", lambda: True)
    monkeypatch.setattr(ingest.gmail_reader, "fetch_replies", fetch)
    monkeypatch.setattr(settings, "quote_ingest_lookback_days", 7)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    assert seen["lookback"] == 7


def test_gmail_query_quotes_addresses_and_clamps_lookback(monkeypatch):
    queries = []

    class Svc:
        def users(self):
            outer = self

            class M:
                def list(self, userId, q, maxResults):
                    queries.append(q)
                    return _Exec(lambda: {"messages": []})

            class U:
                def messages(self):
                    return M()

            return U()

    monkeypatch.setattr(gmail_reader, "_service", lambda: Svc())
    gmail_reader.fetch_replies(["sales+bids@pipe.co", "B@X.COM"], lookback_days=0)
    assert queries == ['(from:"b@x.com" OR from:"sales+bids@pipe.co") newer_than:1d']


# ============================================================ conversation
def _rfq_dict(**over):
    base = {"id": "r1", "projectId": "p1", "package": "water", "status": "Awaiting",
            "statusTone": "warn", "subject": "RFQ: Water", "body": "please quote",
            "recipients": [{"email": "s@x.com", "threadId": "thr-1", "sentMessageId": "m-1"}]}
    base.update(over)
    return base


def test_conversation_reports_a_failed_live_read_instead_of_pretending(monkeypatch, auth):
    client, headers = auth
    from app.db import SessionLocal

    monkeypatch.setattr(rfq_conversation, "gmail_configured", lambda: True)

    def boom(thread_id):
        raise gmail_reader.GmailReadUnavailable("Gmail is rate limiting this mailbox (HTTP 429) — wait a few minutes and retry.")

    monkeypatch.setattr(rfq_conversation.gmail_reader, "fetch_thread", boom)
    monkeypatch.setattr(rfq_conversation.quotes_repo, "list_quotes", lambda *a, **k: [])
    db = SessionLocal()
    try:
        me = client.get("/api/auth/me", headers=headers).json()
        conv = rfq_conversation.build_conversation(db, me["organizationId"], _rfq_dict())
    finally:
        db.close()
    assert conv["gmail"] is False and conv["configured"] is True
    assert "HTTP 429" in conv["readError"]
    assert conv["thread"][0]["dir"] == "out" and conv["thread"][0]["body"] == "please quote"


def test_conversation_with_no_gmail_thread_is_local_without_an_error(monkeypatch, auth):
    client, headers = auth
    from app.db import SessionLocal

    monkeypatch.setattr(rfq_conversation, "gmail_configured", lambda: True)
    monkeypatch.setattr(rfq_conversation.quotes_repo, "list_quotes", lambda *a, **k: [])
    db = SessionLocal()
    try:
        me = client.get("/api/auth/me", headers=headers).json()
        conv = rfq_conversation.build_conversation(
            db, me["organizationId"],
            _rfq_dict(recipients=[{"email": "s@x.com", "threadId": "mock-abc", "sentMessageId": "mock-abc"}]),
        )
    finally:
        db.close()
    assert conv["gmail"] is False and conv["readError"] is None and conv["configured"] is True


def test_conversation_labels_our_messages_by_mailbox_and_member_addresses(monkeypatch, auth):
    client, headers = auth
    from app.db import SessionLocal

    monkeypatch.setattr(settings, "gmail_sender_address", "bids@ws.com")
    client.patch("/api/auth/me", headers=headers, json={"ccEmail": "pm.copy@own.com"})
    emails = [
        gmail_reader.ThreadEmail("a", "t", "bids@ws.com", "Jane Doe — Acme", "RFQ: Water", 1, "please quote"),
        gmail_reader.ThreadEmail("b", "t", "s@x.com", "Sales", "Re: RFQ: Water", 2, "$5"),
        gmail_reader.ThreadEmail("c", "t", "PM@example.com", "PM", "Re: RFQ: Water", 3, "thanks"),  # login address
        gmail_reader.ThreadEmail("d", "t", "pm.copy@own.com", "PM", "Re: RFQ: Water", 4, "one more thing"),
    ]
    db = SessionLocal()
    try:
        me = client.get("/api/auth/me", headers=headers).json()
        ours = rfq_conversation._known_sender_addrs(db, me["organizationId"])
    finally:
        db.close()
    thread = rfq_conversation._emails_to_thread(emails, ours)
    assert [t["dir"] for t in thread] == ["out", "in", "out", "out"]
    assert thread[1]["who"] == "Sales" and thread[0]["subject"] == "RFQ: Water" and thread[1]["subject"] is None


# ============================================================ award notify
class _Recorder:
    mocked = True

    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    def send(self, to, subject, body, *, from_addr, cc=None, thread_id=None, in_reply_to=None, attachments=None):
        if to in self.fail_for:
            raise rfq_sender.GmailUnavailable("Gmail is rate limiting this mailbox (HTTP 429) — wait a few minutes and retry.")
        self.sent.append({"to": to, "subject": subject, "thread_id": thread_id, "cc": cc})
        return rfq_sender.SentMessage(message_id=f"out-{len(self.sent)}", thread_id=thread_id or "t")


def _q(sid, name, email, rfq_id="rfq1", status="received"):
    return {"supplierId": sid, "supplierName": name, "supplierEmail": email, "freight": 10.0,
            "rfqId": rfq_id, "status": status,
            "lineItems": [{"name": "Pipe", "qty": "1 EA", "unitPrice": 5.0, "extended": 5.0, "leadDays": 3}]}


def test_award_declines_each_losing_supplier_once_and_records_outbound_ids(monkeypatch):
    quotes = [_q("a", "Alpha", "alpha@x.com"), _q("b", "Beta", "beta@x.com"), _q("b", "Beta", "beta@x.com")]
    rfq = {"subject": "RFQ: Water", "recipients": [
        {"email": "alpha@x.com", "threadId": "thr-a", "sentMessageId": "m-a"},
        {"email": "beta@x.com", "threadId": "thr-b", "sentMessageId": "m-b"},
    ]}
    monkeypatch.setattr(award_notify.quotes_repo, "list_quotes", lambda *a, **k: quotes)
    monkeypatch.setattr(award_notify.rfqs_repo, "get_rfq", lambda *a, **k: rfq)
    recorded = []
    monkeypatch.setattr(award_notify.rfqs_repo, "record_outbound_message",
                        lambda db, org, rid, email, mid: recorded.append((rid, email, mid)))
    rec = _Recorder()
    out = award_notify.notify_award(
        None, org_id="o", project_id="p", package="water", package_label="Water",
        summary={"selections": {"Pipe": "a"}, "supplierIds": {"a"}},
        buyer=SimpleNamespace(name="PM", company="Co", cc_email="pm@co.com"), sender=rec,
    )
    assert [m["to"] for m in rec.sent] == ["alpha@x.com", "beta@x.com"]
    assert [m["thread_id"] for m in rec.sent] == ["thr-a", "thr-b"]
    assert all(m["subject"] == "Re: RFQ: Water" and m["cc"] == "pm@co.com" for m in rec.sent)
    assert len(out["declined"]) == 1 and out["failed"] == []
    assert recorded == [("rfq1", "alpha@x.com", "out-1"), ("rfq1", "beta@x.com", "out-2")]


def test_award_route_reports_notification_failures(project, monkeypatch):
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=2)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    loser_email = r.json()["recipients"][1]["email"]
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    quotes = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert len(quotes) == 2
    rec = _Recorder(fail_for={loser_email})
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: rec)
    r = client.post(f"/api/projects/{pid}/packages/{bom_id}/award", headers=headers, json={"selections": {}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "awarded"
    assert out["notifyFailed"] and out["notifyFailed"][0]["email"] == loser_email
    assert "HTTP 429" in out["notifyFailed"][0]["error"]
    assert "could not be sent" in out["message"] and "HTTP 429" in out["message"]
    assert out["notified"] + out["declined"] + len(out["notifyFailed"]) == 2
    # The ingest skip-list now includes the notice we did send.
    stored = client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()
    ids = [i for rcp in stored["recipients"] for i in (rcp.get("outboundMessageIds") or [])]
    assert ids == ["out-1"]


def test_failed_award_notifications_are_recorded_and_can_be_resent(project, monkeypatch):
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=2)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    emails = [x["email"] for x in r.json()["recipients"]]
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    dead = _Recorder(fail_for=set(emails))
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: dead)
    r = client.post(f"/api/projects/{pid}/packages/{bom_id}/award", headers=headers, json={"selections": {}})
    assert r.status_code == 200 and len(r.json()["notifyFailed"]) == 2
    assert "2 notifications could not be sent" in r.json()["message"]
    dec = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json()[0]
    assert sorted(f["email"] for f in dec["notifications"]["failed"]) == sorted(emails)
    assert dec["notifications"]["notified"] == [] and dec["notifications"]["declined"] == []

    # Token fixed → re-send just the failed ones; the award is untouched.
    ok = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: ok)
    r = client.post(f"/api/projects/{pid}/packages/{bom_id}/award/notify", headers=headers, json={})
    assert r.status_code == 200, r.text
    assert r.json()["notified"] + r.json()["declined"] == 2 and r.json()["notifyFailed"] == []
    assert sorted(m["to"] for m in ok.sent) == sorted(emails)
    dec = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json()
    assert len(dec) == 1 and dec[0]["notifications"]["failed"] == []
    assert len(dec[0]["notifications"]["notified"]) + len(dec[0]["notifications"]["declined"]) == 2
    # Nothing left to re-send.
    assert client.post(f"/api/projects/{pid}/packages/{bom_id}/award/notify", headers=headers, json={}).status_code == 409
    # …unless everyone is re-notified explicitly.
    r = client.post(f"/api/projects/{pid}/packages/{bom_id}/award/notify", headers=headers, json={"all": True})
    assert r.status_code == 200 and len(ok.sent) == 4


def test_re_award_withdraws_the_previous_po_and_supersedes_the_decision(project, monkeypatch):
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=2)
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    quotes = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    cmp = client.get(f"/api/projects/{pid}/packages/{bom_id}/line-comparison", headers=headers).json()
    sup_a, sup_b = [s["id"] for s in cmp["suppliers"]][:2]
    lines = [r["name"] for r in cmp["lines"]]
    rec = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: rec)
    url = f"/api/projects/{pid}/packages/{bom_id}/award"
    r = client.post(url, headers=headers, json={"selections": {ln: sup_a for ln in lines}})
    assert r.status_code == 200, r.text
    assert r.json()["withdrawn"] == 0 and len(rec.sent) == 2
    rec.sent.clear()

    r = client.post(url, headers=headers, json={"selections": {ln: sup_b for ln in lines}, "supersede": True})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["withdrawn"] == 1 and out["notified"] == 1
    assert "PO is withdrawn" in out["message"]
    decisions = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json()
    by_status = {d["status"]: d for d in decisions}
    assert sorted(by_status) == ["active", "superseded"]
    assert by_status["superseded"]["supersededBy"] == by_status["active"]["id"]
    assert len(by_status["active"]["notifications"]["withdrawn"]) == 1
    assert decisions[0]["status"] == "active"  # newest first


def test_withdrawn_notice_names_the_earlier_order():
    body = award_notify._withdrawn_body(
        "Alpha Supply", "Water", {"createdAt": "2026-09-10T10:00:00", "total": 47500.0, "poCount": 1},
        SimpleNamespace(name="PM", company="Co"),
    )
    assert "Please disregard the purchase order for Water issued on 2026-09-10 ($47,500.00)" in body
    assert "Do not ship or invoice" in body


def test_award_ignores_superseded_and_needs_review_quotes(project, monkeypatch):
    from app.db import SessionLocal
    from app.repositories import quotes as quotes_repo

    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=2)
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    me = client.get("/api/auth/me", headers=headers).json()
    db = SessionLocal()
    try:
        quotes = quotes_repo.list_quotes(db, me["organizationId"], pid, bom_id)
        loser = quotes[1]
        # An older revision from the winner and an unpriced reply from a third party.
        quotes_repo.create_quote(db, me["organizationId"], project_id=pid, package=bom_id,
                                 package_label="x", rfq_id=rfq["id"], supplier_id=quotes[0]["supplierId"],
                                 supplier_name=quotes[0]["supplierName"], supplier_email=quotes[0]["supplierEmail"],
                                 total=999999.0, status="superseded", source="gmail", source_message_id="old")
        quotes_repo.create_quote(db, me["organizationId"], project_id=pid, package=bom_id,
                                 package_label="x", rfq_id=rfq["id"], supplier_id="ghost",
                                 supplier_name="Ghost Co", supplier_email="ghost@x.com",
                                 status="needs_review", source="gmail", source_message_id="nr")
    finally:
        db.close()
    rec = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: rec)
    r = client.post(f"/api/projects/{pid}/packages/{bom_id}/award", headers=headers, json={"selections": {}})
    assert r.status_code == 200, r.text
    assert sorted(m["to"] for m in rec.sent) == sorted([quotes[0]["supplierEmail"], loser["supplierEmail"]])
    db = SessionLocal()
    try:
        by_status = {}
        for q in quotes_repo.list_quotes(db, me["organizationId"], pid, bom_id, include_inactive=True):
            by_status.setdefault(q["status"], []).append(q["supplierName"])
    finally:
        db.close()
    assert by_status["superseded"] == [quotes[0]["supplierName"]]  # untouched by the award flip
    assert by_status["needs_review"] == ["Ghost Co"]


# ================================================================= invites
def test_invite_send_failure_is_reported_with_the_reason(auth, monkeypatch):
    client, headers = auth
    from app.api.routes import team as team_routes

    class Live(_Recorder):
        mocked = False

    monkeypatch.setattr(team_routes.rfq_sender, "is_configured", lambda: True)
    monkeypatch.setattr(team_routes.rfq_sender, "get_sender", lambda: Live(fail_for={"new@x.com"}))
    r = client.post("/api/team/invites", headers=headers, json={"email": "new@x.com"})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["emailed"] is False and "HTTP 429" in inv["emailError"]
    # Delivery failed → the inviter gets the link to pass on by hand.
    assert inv["acceptUrl"] and "/#/invite/" in inv["acceptUrl"]
    # The team list reports the real outcome, not "a provider exists".
    listed = client.get("/api/team", headers=headers).json()["invites"][0]
    assert listed["emailed"] is False and "HTTP 429" in listed["emailError"] and listed["acceptUrl"]
    # A successful resend clears the error and hides the link again.
    monkeypatch.setattr(team_routes.rfq_sender, "get_sender", lambda: Live())
    r = client.post(f"/api/team/invites/{inv['id']}/resend", headers=headers)
    out = r.json()
    assert r.status_code == 200 and out["emailed"] is True and out["emailError"] is None
    assert out["acceptUrl"] is None and out["emailedAt"]
    assert client.get("/api/team", headers=headers).json()["invites"][0]["emailed"] is True


def test_test_email_surfaces_a_readable_gmail_error(auth, monkeypatch):
    client, headers = auth
    from app.api.routes import auth as auth_routes

    class Dead:
        mocked = False

        def send(self, *a, **kw):
            raise rfq_sender.GmailUnavailable(rfq_sender.describe_gmail_error(
                Exception("('invalid_grant: Bad Request', {'error': 'invalid_grant'})")))

    monkeypatch.setattr(auth_routes.rfq_sender, "get_sender", lambda: Dead())
    r = client.post("/api/auth/test-email", headers=headers)
    assert r.status_code == 502
    assert "invalid_grant" in r.json()["detail"] and "re-mint" in r.json()["detail"]


# ============================================================ provider health
def test_email_config_reports_llm_and_gmail_health(auth, monkeypatch):
    client, headers = auth
    from app.services import llm_health

    llm_health.reset()
    rfq_sender.reset_gmail_state()
    cfg = client.get("/api/auth/email-config", headers=headers).json()
    assert cfg["llm"]["configured"] is False and cfg["llm"]["lastError"] is None
    assert cfg["gmail"] == {"lastError": None, "lastErrorAt": None, "lastOkAt": None}

    # A parser failure is recorded once at WARNING and shows up in Settings.
    monkeypatch.setattr(settings, "openai_api_key", "sk-proj-xyz")
    monkeypatch.setattr(settings, "openai_base_url", "https://openrouter.ai/api/v1")
    from app.services.quotes import parser

    class Boom:
        def __init__(self, **kw):
            raise RuntimeError("Error code: 401 - {'error': {'message': 'Missing Authentication header'}}")

    import openai
    monkeypatch.setattr(openai, "OpenAI", Boom)
    assert parser._llm_parse("Total $5") is None
    assert parser._llm_parse("Total $6") is None  # second failure: no second WARNING
    cfg = client.get("/api/auth/email-config", headers=headers).json()
    assert cfg["llm"]["configured"] is True
    assert "401" in cfg["llm"]["lastError"] and "sk-proj" in cfg["llm"]["lastError"]
    assert cfg["llm"]["lastErrorWhere"] == "quote parser"

    # A dead Gmail token is recorded too.
    class Dead:
        mocked = False

        def send(self, *a, **kw):
            rfq_sender.record_gmail_failure("Gmail connection expired or was revoked (invalid_grant) — re-mint")
            raise rfq_sender.GmailUnavailable("Gmail connection expired or was revoked (invalid_grant) — re-mint")

    from app.api.routes import auth as auth_routes
    monkeypatch.setattr(auth_routes.rfq_sender, "get_sender", lambda: Dead())
    assert client.post("/api/auth/test-email", headers=headers).status_code == 502
    cfg = client.get("/api/auth/email-config", headers=headers).json()
    assert "invalid_grant" in cfg["gmail"]["lastError"]
    # …and the failed test send is in the audit log.
    audit = client.get("/api/audit?action=email.test_failed", headers=headers).json()
    assert audit and "invalid_grant" in (audit[0].get("detail") or {}).get("error", "")
    llm_health.reset()
    rfq_sender.reset_gmail_state()


def test_llm_failure_logs_a_warning_once(caplog, monkeypatch):
    from app.services import llm_health

    llm_health.reset()
    with caplog.at_level("INFO", logger="procureai.llm"):
        llm_health.record_failure(RuntimeError("401 Unauthorized"), "quote parser")
        llm_health.record_failure(RuntimeError("401 Unauthorized"), "quote parser")
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1 and "quote parser" in warnings[0].getMessage()
    llm_health.record_success()
    assert llm_health.status()["lastError"] is None
    llm_health.reset()


def test_providers_health_probe_reports_each_provider(auth, monkeypatch):
    client, headers = auth
    from app.api.routes import health as health_routes

    # Unconfigured: both fail with the reason, nothing is called.
    r = client.get("/api/health/providers", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "PROCUREAI_GMAIL_CLIENT_ID" in body["gmail"]["error"]
    assert "PROCUREAI_OPENAI_API_KEY" in body["llm"]["error"]

    # Configured and answering: the probe compares the mailbox to the sender address.
    monkeypatch.setattr(health_routes.rfq_sender, "probe_gmail", lambda: {
        "ok": False, "error": "The connected mailbox is other@gmail.com but PROCUREAI_GMAIL_SENDER_ADDRESS is bids@ws.com — Gmail will rewrite From: to the connected account; set the variable to other@gmail.com.",
        "emailAddress": "other@gmail.com", "senderAddress": "bids@ws.com", "senderAddressMatches": False,
        "sendScope": True, "readScope": True,
    })
    monkeypatch.setattr(health_routes.llm_health, "probe", lambda: {"ok": True, "error": None, "model": "gpt-4.1"})
    body = client.get("/api/health/providers", headers=headers).json()
    assert body["ok"] is False and body["llm"]["ok"] is True
    assert body["gmail"]["senderAddressMatches"] is False and "rewrite From" in body["gmail"]["error"]
    # Rate limited: 3/minute.
    client.get("/api/health/providers", headers=headers)
    assert client.get("/api/health/providers", headers=headers).status_code == 429
    # Unauthenticated: refused.
    assert client.get("/api/health/providers").status_code in (401, 403)


def test_probe_gmail_unconfigured_never_touches_the_network():
    out = rfq_sender.probe_gmail()
    assert out["ok"] is False and "Not configured" in out["error"] and out["sendScope"] is False


# ================================================================== metrics
def test_metrics_do_not_count_a_failed_send_or_superseded_quotes(project, monkeypatch):
    """Dashboard / overview / project rows: an RFQ nobody received is not
    'sent', and superseded revisions / needs-review replies are not quotes."""
    from app.db import SessionLocal
    from app.repositories import quotes as quotes_repo

    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=1)

    class Dead:
        mocked = True

        def send(self, *a, **kw):
            raise rfq_sender.GmailUnavailable("Gmail connection expired or was revoked (invalid_grant) — re-mint")

    monkeypatch.setattr(rfq_sender, "get_sender", lambda: Dead())
    assert client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers).json()["status"] == "Send failed"

    def cards():
        return {c["label"]: c for c in client.get(f"/api/projects/{pid}", headers=headers).json()["overviewCards"]}

    def dash():
        return {m["label"]: m for m in client.get("/api/dashboard", headers=headers).json()["metrics"]}

    c = cards()
    assert c["RFQs sent"]["value"] == "0" and "1 failed to send" in c["RFQs sent"]["sub"]
    assert dash()["RFQs out"]["value"] == "0"
    row = next(p for p in client.get("/api/projects", headers=headers).json() if p["id"] == pid)
    assert row["rfqs"] == 0 and row["stage"] == "Sourcing"
    pk = {p["name"]: p for p in client.get(f"/api/projects/{pid}", headers=headers).json()["packages"]}
    assert pk["Hydrants Package"]["stage"] == "RFQ drafted"

    # Retry delivers; then a superseded revision and a needs-review reply are
    # stored beside the one real quote.
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: rfq_sender.MockSender())
    assert client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers).json()["status"] == "Awaiting"
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    me = client.get("/api/auth/me", headers=headers).json()
    db = SessionLocal()
    try:
        for status, mid in (("superseded", "old"), ("needs_review", "nr")):
            quotes_repo.create_quote(db, me["organizationId"], project_id=pid, package=bom_id, package_label="x",
                                     rfq_id=rfq["id"], supplier_id="ghost", supplier_name="Ghost", supplier_email="g@x.com",
                                     total=1.0 if status == "superseded" else None, status=status, source="gmail", source_message_id=mid)
    finally:
        db.close()
    assert cards()["Quotes received"]["value"] == "1"
    assert dash()["Quotes received"]["value"] == "1"
    assert cards()["RFQs sent"]["value"] == "1"


def test_mock_sends_are_labelled_as_logged_not_delivered(project):
    client, headers, pid = project
    _, rfq = _rfq_ready(client, headers, pid, n=1)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200
    rcp = r.json()["recipients"][0]
    assert rcp["sendStatus"] == "sent" and rcp["mock"] is True
    conv = client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}/conversation", headers=headers).json()
    assert conv["gmail"] is False and conv["thread"][0]["time"] == "Logged only (mock \u2014 not delivered)"
