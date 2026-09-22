"""Email workflow robustness: send errors, ingest idempotency / supersede /
needs-review, conversation honesty, award notifications and config
truthfulness.

Provider creds are force-blanked in conftest, so nothing here can reach
AgentMail: sends go through a recording sender and replies are stored rows
(what the webhook would have written).
"""
from types import SimpleNamespace

import pytest

from app.config import settings
from app.db import SessionLocal
from app.repositories import inbound_emails as inbound_repo
from app.services.email import text as email_text
from app.services.quotes import ingest, pdf_text
from app.services.quotes.models import ParsedQuote, ParsedQuoteLine
from app.services.rfq import award_notify
from app.services.rfq import conversation as rfq_conversation
from app.services.rfq import sender as rfq_sender
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search

_RATE_LIMITED = "AgentMail is rate limiting this organization (HTTP 429): wait a minute and retry."
_BAD_KEY = "AgentMail rejected the API key (HTTP 401): check PROCUREAI_AGENTMAIL_API_KEY (docs/email-setup.md)."


def _org_id(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["organizationId"]


# ============================================================== configuration
@pytest.mark.parametrize("key, configured, missing", [
    ("am_live_key", True, []),
    ("", False, ["PROCUREAI_AGENTMAIL_API_KEY"]),
    ("   ", False, ["PROCUREAI_AGENTMAIL_API_KEY"]),
])
def test_email_config_is_truthful_for_every_combination(monkeypatch, key, configured, missing):
    monkeypatch.setattr(settings, "agentmail_api_key", key)
    cfg = rfq_sender.email_config()
    assert cfg["configured"] is configured and cfg["mocked"] is (not configured)
    assert cfg["missing"] == missing
    assert cfg["inboxAddress"] is None
    assert rfq_sender.is_configured() is configured


def test_email_config_endpoint_lists_missing_vars(auth):
    client, headers = auth
    cfg = client.get("/api/auth/email-config", headers=headers).json()
    assert cfg["configured"] is False
    assert "PROCUREAI_AGENTMAIL_API_KEY" in cfg["missing"]
    assert cfg["inboxAddress"] is None
    assert cfg["fromHeader"].endswith(f"<{rfq_sender.UNCONFIGURED_SENDER_ADDRESS}>")


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
            raise rfq_sender.EmailUnavailable(_BAD_KEY)

    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: Dead())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "Send failed"
    for rec in body["recipients"]:
        assert rec["sendStatus"] == "failed"
        assert "HTTP 401" in rec["sendError"] and "PROCUREAI_AGENTMAIL_API_KEY" in rec["sendError"]
        assert "status_code" not in rec["sendError"]
    # Not stuck: a retry with a working sender delivers to everyone.
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: rfq_sender.MockSender())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "Awaiting"
    for rec in r.json()["recipients"]:
        assert rec["sendStatus"] == "sent" and rec["threadId"] and rec["sentAt"]
        assert rec["messageId"] == rec["sentMessageId"]


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
    record of that send: a retry would email them again. The recipient
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

    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: FailSecond())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "Send failed"
    assert [[x.get("sendStatus") for x in snap] for snap in snapshots] == [["sent", None], ["sent", "failed"]]


# ============================================================ reply text
@pytest.mark.parametrize("body, expected", [
    ("New: $10\n\nOn Tue, Sep 16, 2026 at 3:00 PM Jane Doe: Acme <bids@ws.com>\nwrote:\n> old $20", "New: $10"),
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
    assert email_text.strip_quoted(body) == expected


def test_html_only_bodies_are_rendered_to_text_without_the_quoted_chain():
    html = "<div>Revised: <b>$47,500</b><br>10 days</div><blockquote>On … wrote: $52,000</blockquote>"
    assert email_text.html_to_text(html) == "Revised: $47,500\n10 days"


def test_addresses_are_parsed_and_rfc2047_decoded():
    raw = "=?utf-8?q?Jane_Doe?= <Bids@WS.com>"
    assert email_text.parse_addr(raw) == "bids@ws.com"
    assert email_text.parse_name(raw) == "Jane Doe"
    assert email_text.parse_name("sales@pipe.co") == "sales@pipe.co"


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
def _store_reply(org_id, mid, frm, text, thread="", rfq_id=None, project_id=None,
                 subject="Re: RFQ", in_reply_to="", attachments=None, kind=None):
    """What the webhook stores for a supplier reply, already attributed."""
    db = SessionLocal()
    try:
        row = inbound_repo.create(
            db, organization_id=org_id, provider_message_id=mid, inbox_id="acme@agentmail.to",
            thread_id=thread, in_reply_to=in_reply_to, from_email=frm.lower(), from_name=frm.split("@")[0],
            subject=subject, text=text, attachments=attachments or [],
            kind=kind or ("rfq_reply" if rfq_id else "unknown"), rfq_id=rfq_id, project_id=project_id,
        )
        return row.id
    finally:
        db.close()


def _live_replies(monkeypatch, parsed_by_text):
    """Route ingest down the live path with a canned parser."""
    monkeypatch.setattr(ingest, "is_configured", lambda: True)
    monkeypatch.setattr(ingest.parser, "parse_quote", lambda text: parsed_by_text(text))


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
    org_id = _org_id(client, headers)

    def parse(text):
        if "$" not in text:
            return ParsedQuote(is_quote=True, supplier_name="Pipe Co", notes="see attached")
        amount = float(text.split("$")[1].split()[0].replace(",", ""))
        return _priced(amount)

    _store_reply(org_id, "r1", sup, "Quote $52,000 total", thread, rfq["id"], pid)
    _store_reply(org_id, "r2", "stranger@nowhere.com", "Quote $1 total", "thr-other")  # unattributed
    _store_reply(org_id, "r3", sup, "Attached is our quote (see PDF)", thread, rfq["id"], pid)  # nothing priced
    _store_reply(org_id, "r4", sup, "Revised quote $47,500 total", thread, rfq["id"], pid)
    _live_replies(monkeypatch, parse)

    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["status"] == "done", st
    assert st["mocked"] is False
    assert (st["ingested"], st["needsReview"], st["superseded"]) == (2, 1, 2)

    rows = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    # Only the latest revision is listed (and it is the best); nothing from the
    # stranger.
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
    # Every stored reply is marked processed; the stranger's stays unknown.
    listed = client.get("/api/inbound", headers=headers).json()
    by_id = {x["providerMessageId"]: x for x in listed}
    assert all(by_id[m]["processedAt"] for m in ("r1", "r3", "r4"))
    assert by_id["r2"]["kind"] == "unknown" and by_id["r2"]["processedAt"] is None


def test_unpriced_reply_alone_is_needs_review_not_quoted(project, monkeypatch):
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=1)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    sup = r.json()["recipients"][0]["email"]
    thread = r.json()["recipients"][0]["threadId"]
    _store_reply(_org_id(client, headers), "r1", sup, "Attached.", thread, rfq["id"], pid)
    _live_replies(monkeypatch, lambda text: ParsedQuote(is_quote=True, supplier_name="Pipe Co"))
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
    the same thread. Thread attribution does not care who wrote."""
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=1)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    rcp = r.json()["recipients"][0]
    org_id = _org_id(client, headers)
    _store_reply(org_id, "est-1", "jane.estimator@supplier.example", "Quote $61,000 total",
                 rcp["threadId"], rfq["id"], pid)
    _live_replies(monkeypatch, lambda text: _priced(61000.0, name="Supplier Inc"))
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["status"] == "done" and st["ingested"] == 1, st
    rows = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert rows[0]["total"] == "$61,000"
    assert client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()["status"] == "Quoted"

    rec = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: rec)
    r = client.post(f"/api/projects/{pid}/packages/{bom_id}/award", headers=headers, json={"selections": {}})
    assert r.status_code == 200, r.text
    # The PO goes to the address that quoted, as a reply to the RFQ we sent
    # to sales@ (mock ids carry no provider message to reply to).
    assert rec.sent == [{"to": "jane.estimator@supplier.example", "subject": f"Re: {rfq['subject']}",
                         "thread_id": rcp["threadId"], "cc": None}]


def test_reply_in_a_different_known_thread_is_not_attributed():
    """A supplier on ONE RFQ here replied to another project's RFQ (thread
    known, different): the single-RFQ fallback must not claim it."""
    meta = {"rfq_id": "rB", "thread_id": "threadB", "subject": "RFQ: Water: Project B"}
    msg = SimpleNamespace(thread_id="threadA", subject="Re: RFQ: Sewer: Project A", message_id="m", from_email="s@x.com")
    assert ingest._match_rfq([meta], msg) is None
    promo = SimpleNamespace(thread_id="threadZ", subject="Spring promo", message_id="m2", from_email="s@x.com")
    assert ingest._match_rfq([meta], promo) is None
    # Legacy send with no thread on record: the single-RFQ rule still applies.
    legacy = {"rfq_id": "rB", "thread_id": "", "subject": "RFQ: Water: Project B"}
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

    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: Flaky())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.json()["status"] == "Send failed"
    org_id = _org_id(client, headers)
    # A reply "from" the supplier who never got the RFQ matches no sent RFQ
    # (no thread), so the row is skipped and marked for a human.
    _store_reply(org_id, "ghost", fail_email, "Quote $5 total", "", None, pid, kind="rfq_reply")
    _live_replies(monkeypatch, lambda text: _priced(5.0))
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["ingested"] == 0
    row = client.get("/api/inbound", headers=headers).json()[0]
    assert row["processedAt"] is None and "matches" in row["error"]


def test_unit_priced_reply_is_totalled_with_the_rfq_quantities(project, monkeypatch):
    """Regex path (no model configured): 'hydrant $3,150 each, valve $1,240
    each, freight $900' against an RFQ asking for 5 hydrants and 9 valves."""
    client, headers, pid = project
    bom_id, rfq = _rfq_ready(client, headers, pid, n=1)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    rcp = r.json()["recipients"][0]
    _store_reply(_org_id(client, headers), "u1", rcp["email"],
                 "Fire hydrant $3,150.00 each, 8-inch gate valve $1,240 each, freight $900, 4 weeks",
                 rcp["threadId"], rfq["id"], pid)
    monkeypatch.setattr(ingest, "is_configured", lambda: True)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["ingested"] == 1, st
    q = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()[0]
    assert (q["amount"], q["freight"], q["total"], q["lead"]) == ("$26,910", "$900", "$27,810", "28 days")


def test_pdf_attachment_text_feeds_the_parser(project, monkeypatch, tmp_path):
    """A quote that lives in the attached PDF, not the body."""
    fitz = pytest.importorskip("fitz")
    client, headers, pid = project
    _, rfq = _rfq_ready(client, headers, pid, n=1)
    rcp = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers).json()["recipients"][0]
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Grand total $12,345.00 delivered")
    path = tmp_path / "quote.pdf"
    path.write_bytes(doc.tobytes())
    _store_reply(_org_id(client, headers), "pdf1", rcp["email"], "Please see attached.",
                 rcp["threadId"], rfq["id"], pid,
                 attachments=[{"filename": "quote.pdf", "mimeType": "application/pdf",
                               "size": path.stat().st_size, "locator": str(path)}])
    monkeypatch.setattr(ingest, "is_configured", lambda: True)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    q = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()[0]
    assert q["total"] == "$12,345"


def test_stored_replies_take_precedence_over_mock_quotes(project, monkeypatch):
    """A locally forged webhook delivery (no API key) must not be buried
    under simulated quotes when the dashboard checks for replies."""
    client, headers, pid = project
    _, rfq = _rfq_ready(client, headers, pid, n=2)
    rcp = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers).json()["recipients"][0]
    _store_reply(_org_id(client, headers), "real-1", rcp["email"], "Total $9,000 delivered",
                 rcp["threadId"], rfq["id"], pid)
    assert not rfq_sender.is_configured()
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["mocked"] is False and st["ingested"] == 1
    rows = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert [r["total"] for r in rows] == ["$9,000"]


# ============================================================ conversation
def _rfq_dict(**over):
    base = {"id": "r1", "projectId": "p1", "package": "water", "status": "Awaiting",
            "statusTone": "warn", "subject": "RFQ: Water", "body": "please quote",
            "recipients": [{"email": "s@x.com", "threadId": "thr-1", "sentMessageId": "m-1",
                            "sendStatus": "sent", "sentAt": "2026-09-16T15:00:00+00:00"}]}
    base.update(over)
    return base


def test_conversation_is_local_before_any_reply_arrives(monkeypatch, auth):
    client, headers = auth
    monkeypatch.setattr(rfq_conversation.quotes_repo, "list_quotes", lambda *a, **k: [])
    db = SessionLocal()
    try:
        conv = rfq_conversation.build_conversation(db, _org_id(client, headers), _rfq_dict())
    finally:
        db.close()
    assert conv["live"] is False and conv["configured"] is False
    assert conv["thread"][0]["dir"] == "out" and conv["thread"][0]["body"] == "please quote"


def test_conversation_shows_stored_replies_and_labels_our_own_messages(monkeypatch, auth):
    client, headers = auth
    org_id = _org_id(client, headers)
    client.patch("/api/auth/me", headers=headers, json={"ccEmail": "pm.copy@own.com"})
    rfq = _rfq_dict()
    for i, (frm, name, text) in enumerate([
        ("s@x.com", "Sales", "$5 total"),
        ("PM@example.com", "PM", "thanks"),  # login address
        ("pm.copy@own.com", "PM", "one more thing\n\nOn Tue, Sep 16 Sales <s@x.com> wrote:\n> $5"),
    ]):
        _store_reply(org_id, f"c{i}", frm, text, "thr-1", rfq["id"], "p1")
        # from_name derived by _store_reply is the local part; set the real one.
    db = SessionLocal()
    try:
        for row in inbound_repo.list_for_rfq(db, org_id, rfq["id"]):
            row.from_name = {"s@x.com": "Sales", "pm@example.com": "PM", "pm.copy@own.com": "PM"}[row.from_email]
        db.commit()
        conv = rfq_conversation.build_conversation(db, org_id, rfq)
    finally:
        db.close()
    assert conv["live"] is True
    thread = conv["thread"]
    assert [t["dir"] for t in thread] == ["out", "in", "out", "out"]
    assert thread[0]["subject"] == "RFQ: Water" and thread[0]["time"] == "Sep 16, 3:00 PM"
    assert thread[1]["who"] == "Sales" and thread[1]["subject"] is None
    assert thread[3]["body"] == "one more thing"  # quoted chain stripped


# ============================================================ award notify
class _Recorder:
    mocked = True

    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    def send(self, to, subject, body, *, from_addr, cc=None, thread_id=None, in_reply_to=None,
             attachments=None, reply_to=None):
        if to in self.fail_for:
            raise rfq_sender.EmailUnavailable(_RATE_LIMITED)
        self.sent.append({"to": to, "subject": subject, "thread_id": thread_id, "cc": cc,
                          **({"in_reply_to": in_reply_to} if in_reply_to else {})})
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
    assert [m["in_reply_to"] for m in rec.sent] == ["m-a", "m-b"]  # replies to the RFQ we sent
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
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: rec)
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
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: dead)
    r = client.post(f"/api/projects/{pid}/packages/{bom_id}/award", headers=headers, json={"selections": {}})
    assert r.status_code == 200 and len(r.json()["notifyFailed"]) == 2
    assert "2 notifications could not be sent" in r.json()["message"]
    dec = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json()[0]
    assert sorted(f["email"] for f in dec["notifications"]["failed"]) == sorted(emails)
    assert dec["notifications"]["notified"] == [] and dec["notifications"]["declined"] == []

    # Token fixed → re-send just the failed ones; the award is untouched.
    ok = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: ok)
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
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: rec)
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
                                 total=999999.0, status="superseded", source="agentmail", source_message_id="old")
        quotes_repo.create_quote(db, me["organizationId"], project_id=pid, package=bom_id,
                                 package_label="x", rfq_id=rfq["id"], supplier_id="ghost",
                                 supplier_name="Ghost Co", supplier_email="ghost@x.com",
                                 status="needs_review", source="agentmail", source_message_id="nr")
    finally:
        db.close()
    rec = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: rec)
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

    monkeypatch.setattr(team_routes.rfq_sender, "get_sender", lambda *a, **k: Live(fail_for={"new@x.com"}))
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
    monkeypatch.setattr(team_routes.rfq_sender, "get_sender", lambda *a, **k: Live())
    r = client.post(f"/api/team/invites/{inv['id']}/resend", headers=headers)
    out = r.json()
    assert r.status_code == 200 and out["emailed"] is True and out["emailError"] is None
    assert out["acceptUrl"] is None and out["emailedAt"]
    assert client.get("/api/team", headers=headers).json()["invites"][0]["emailed"] is True


def test_test_email_surfaces_a_readable_provider_error(auth, monkeypatch):
    client, headers = auth
    from app.api.routes import auth as auth_routes

    class Dead:
        mocked = False

        def send(self, *a, **kw):
            raise rfq_sender.EmailUnavailable(_BAD_KEY)

    monkeypatch.setattr(auth_routes.rfq_sender, "get_sender", lambda *a, **k: Dead())
    r = client.post("/api/auth/test-email", headers=headers)
    assert r.status_code == 502
    assert "HTTP 401" in r.json()["detail"] and "PROCUREAI_AGENTMAIL_API_KEY" in r.json()["detail"]


# ============================================================ provider health
def test_email_config_reports_llm_and_agentmail_health(auth, monkeypatch):
    client, headers = auth
    from app.services import llm_health

    llm_health.reset()
    rfq_sender.reset_state()
    cfg = client.get("/api/auth/email-config", headers=headers).json()
    assert cfg["llm"]["configured"] is False and cfg["llm"]["lastError"] is None
    assert cfg["agentmail"] == {"lastError": None, "lastErrorAt": None, "lastOkAt": None}

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

    # A rejected API key is recorded too.
    class Dead:
        mocked = False

        def send(self, *a, **kw):
            rfq_sender.record_failure(_BAD_KEY)
            raise rfq_sender.EmailUnavailable(_BAD_KEY)

    from app.api.routes import auth as auth_routes
    monkeypatch.setattr(auth_routes.rfq_sender, "get_sender", lambda *a, **k: Dead())
    assert client.post("/api/auth/test-email", headers=headers).status_code == 502
    cfg = client.get("/api/auth/email-config", headers=headers).json()
    assert "HTTP 401" in cfg["agentmail"]["lastError"]
    # ...and the failed test send is in the audit log.
    audit = client.get("/api/audit?action=email.test_failed", headers=headers).json()
    assert audit and "HTTP 401" in (audit[0].get("detail") or {}).get("error", "")
    llm_health.reset()
    rfq_sender.reset_state()


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
    assert "PROCUREAI_AGENTMAIL_API_KEY" in body["email"]["error"]
    assert "PROCUREAI_OPENAI_API_KEY" in body["llm"]["error"]

    # Configured and answering: the probe reports the inbox it resolved.
    monkeypatch.setattr(health_routes.rfq_sender, "probe_email", lambda db, org_id: {
        "ok": True, "error": None, "inboxAddress": "acme@proq.tryproq.dev",
    })
    monkeypatch.setattr(health_routes.llm_health, "probe", lambda: {"ok": True, "error": None, "model": "gpt-4.1"})
    body = client.get("/api/health/providers", headers=headers).json()
    assert body["ok"] is True and body["llm"]["ok"] is True
    assert body["email"]["inboxAddress"] == "acme@proq.tryproq.dev"
    # Rate limited: 3/minute.
    client.get("/api/health/providers", headers=headers)
    assert client.get("/api/health/providers", headers=headers).status_code == 429
    # Unauthenticated: refused.
    assert client.get("/api/health/providers").status_code in (401, 403)


def test_probe_email_unconfigured_never_touches_the_network(auth):
    client, headers = auth
    db = SessionLocal()
    try:
        out = rfq_sender.probe_email(db, _org_id(client, headers))
    finally:
        db.close()
    assert out["ok"] is False and "Not configured" in out["error"] and out["inboxAddress"] is None


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
            raise rfq_sender.EmailUnavailable(_BAD_KEY)

    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: Dead())
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
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: rfq_sender.MockSender())
    assert client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers).json()["status"] == "Awaiting"
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    me = client.get("/api/auth/me", headers=headers).json()
    db = SessionLocal()
    try:
        for status, mid in (("superseded", "old"), ("needs_review", "nr")):
            quotes_repo.create_quote(db, me["organizationId"], project_id=pid, package=bom_id, package_label="x",
                                     rfq_id=rfq["id"], supplier_id="ghost", supplier_name="Ghost", supplier_email="g@x.com",
                                     total=1.0 if status == "superseded" else None, status=status, source="agentmail", source_message_id=mid)
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
    assert conv["live"] is False and conv["thread"][0]["time"] == "Logged only (mock, not delivered)"
