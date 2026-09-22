"""Supplier replies end to end: webhook delivery, attribution to the RFQ by
thread id (or In-Reply-To), quote parsing, the recipient's repliedAt, the
conversation view and the dashboard's "Check for replies"."""
import pytest

from app.db import SessionLocal
from app.models.inbound_email import InboundEmail
from app.models.organization import Organization
from app.repositories import rfqs as rfqs_repo
from app.services.inbound import intake, rfq_replies
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search

INBOX = "acme@proq.tryproq.dev"


@pytest.fixture()
def sent_rfq(project, monkeypatch):
    """An RFQ sent (mock) to two suppliers whose org owns INBOX, with
    provider-looking ids on the recipients. Returns (client, headers, pid, org_id, rfq)."""
    client, headers, pid = project
    org_id = client.get("/api/auth/me", headers=headers).json()["organizationId"]
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:2])
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    rfq = r.json()
    db = SessionLocal()
    try:
        db.get(Organization, org_id).agentmail_inbox_id = INBOX
        db.commit()
        # Pretend the send went through AgentMail (mock ids are never matched).
        for i, rcp in enumerate(rfq["recipients"], 1):
            rcp["messageId"] = rcp["sentMessageId"] = f"<out{i}@agentmail.to>"
            rcp["threadId"] = f"thr_{i}"
        rfqs_repo.save_recipients(db, org_id, rfq["id"], rfq["recipients"])
    finally:
        db.close()
    # Intake belongs to another stream (its stub raises); never a match here.
    monkeypatch.setattr(intake, "attribute", lambda db, row: False)
    return client, headers, pid, org_id, rfq


def _deliver(client, mid, frm, text, thread="", in_reply_to="", subject="Re: RFQ"):
    event = {
        "type": "event", "event_type": "message.received", "event_id": "evt",
        "message": {
            "inbox_id": INBOX, "thread_id": thread, "message_id": mid,
            "from": frm, "to": [INBOX], "subject": subject,
            "text": text, "extracted_text": text, "in_reply_to": in_reply_to,
        },
        "thread": {"inbox_id": INBOX, "thread_id": thread},
    }
    r = client.post("/api/webhooks/agentmail", json=event)
    assert r.status_code == 200, r.text


def _quote_emails(org_id, pid):
    from app.repositories import quotes as quotes_repo

    db = SessionLocal()
    try:
        return [q["supplierEmail"] for q in quotes_repo.list_quotes(db, org_id, pid, include_inactive=True)]
    finally:
        db.close()


def _row(mid) -> InboundEmail:
    db = SessionLocal()
    try:
        return db.query(InboundEmail).filter_by(provider_message_id=mid).one()
    finally:
        db.close()


def test_reply_in_the_rfq_thread_becomes_a_quote(sent_rfq):
    client, headers, pid, org_id, rfq = sent_rfq
    rcp = rfq["recipients"][0]
    _deliver(client, "<r1@pipe.co>", f"Sales <{rcp['email']}>",
             "Fire hydrant $3,150.00 each, 8-inch gate valve $1,240 each, freight $900, 4 weeks",
             thread="thr_1")
    row = _row("<r1@pipe.co>")
    assert row.kind == "rfq_reply" and row.rfq_id == rfq["id"] and row.project_id == pid
    assert row.processed_at is not None and row.error is None
    # The quote is on the project, parsed from THIS message.
    [q] = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert (q["amount"], q["freight"], q["total"]) == ("$26,910", "$900", "$27,810")
    assert _quote_emails(org_id, pid) == [rcp["email"]]
    stored = client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()
    assert stored["status"] == "Quoted"
    # Only the supplier who answered is marked replied.
    by_email = {r["email"]: r for r in stored["recipients"]}
    assert by_email[rcp["email"]]["repliedAt"]
    assert by_email[rfq["recipients"][1]["email"]].get("repliedAt") is None
    # ...and the conversation shows the reply under the RFQ.
    conv = client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}/conversation", headers=headers).json()
    assert conv["live"] is True
    assert [t["dir"] for t in conv["thread"]] == ["out", "in"]
    assert conv["thread"][1]["who"] == "Sales" and "$3,150.00" in conv["thread"][1]["body"]


def test_reply_from_another_address_is_attributed_by_thread(sent_rfq):
    """RFQ to sales@, the estimator answers from her own mailbox in the same
    thread: attribution is by thread, not sender."""
    client, headers, pid, org_id, rfq = sent_rfq
    _deliver(client, "<est@sup>", "Jane <jane.estimator@supplier.example>", "Total $61,000 delivered", thread="thr_2")
    row = _row("<est@sup>")
    assert row.kind == "rfq_reply" and row.rfq_id == rfq["id"]
    [q] = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert q["total"] == "$61,000"
    assert _quote_emails(org_id, pid) == ["jane.estimator@supplier.example"]


def test_reply_is_attributed_by_in_reply_to_when_the_thread_is_new(sent_rfq):
    """A supplier who starts a fresh thread but keeps the In-Reply-To header
    (some CRMs) still lands on the RFQ."""
    client, headers, pid, org_id, rfq = sent_rfq
    rcp = rfq["recipients"][1]
    _deliver(client, "<crm@sup>", rcp["email"], "Grand total $9,500", thread="thr_new",
             in_reply_to="<out2@agentmail.to>")
    row = _row("<crm@sup>")
    assert row.kind == "rfq_reply" and row.rfq_id == rfq["id"]
    assert client.get(f"/api/projects/{pid}/quotes", headers=headers).json()[0]["total"] == "$9,500"


def test_reply_to_an_award_notice_still_attributes_to_the_rfq(sent_rfq):
    client, headers, pid, org_id, rfq = sent_rfq
    rcp = rfq["recipients"][0]
    db = SessionLocal()
    try:
        rfqs_repo.record_outbound_message(db, org_id, rfq["id"], rcp["email"], "<award@agentmail.to>")
    finally:
        db.close()
    _deliver(client, "<ack@sup>", rcp["email"], "Order acknowledged, total $27,810", thread="thr_x",
             in_reply_to="<award@agentmail.to>")
    assert _row("<ack@sup>").rfq_id == rfq["id"]


def test_unrelated_mail_is_not_attributed(sent_rfq):
    client, headers, pid, org_id, rfq = sent_rfq
    _deliver(client, "<promo@sup>", rfq["recipients"][0]["email"], "Spring promo $1", thread="thr_other",
             in_reply_to="<nothing@elsewhere>")
    row = _row("<promo@sup>")
    assert row.kind == "unknown" and row.rfq_id is None and row.processed_at is None
    assert client.get(f"/api/projects/{pid}/quotes", headers=headers).json() == []
    # Direct check of the attribution rules on the row.
    db = SessionLocal()
    try:
        r = db.get(InboundEmail, row.id)
        assert rfq_replies.attribute(db, r) is False
        r.thread_id = "thr_1"
        assert rfq_replies.attribute(db, r) is True and r.rfq_id == rfq["id"]
        r.rfq_id = None
        r.thread_id = ""
        r.in_reply_to = "<out1@agentmail.to>"
        assert rfq_replies.attribute(db, r) is True and r.rfq_id == rfq["id"]
        # Another org's inbox can never claim it.
        r.rfq_id = None
        r.organization_id = "someone-else"
        assert rfq_replies.attribute(db, r) is False
        db.rollback()
    finally:
        db.close()


def test_a_non_quote_reply_marks_replied_without_a_quote(sent_rfq):
    client, headers, pid, org_id, rfq = sent_rfq
    rcp = rfq["recipients"][0]
    _deliver(client, "<ack@sup>", rcp["email"], "Received, we will send pricing Friday.", thread="thr_1")
    row = _row("<ack@sup>")
    assert row.kind == "rfq_reply" and row.processed_at is not None
    assert client.get(f"/api/projects/{pid}/quotes", headers=headers).json() == []
    stored = client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()
    assert stored["status"] == "Awaiting"
    assert next(r for r in stored["recipients"] if r["email"] == rcp["email"])["repliedAt"]


def test_a_revision_supersedes_and_a_redelivery_is_a_no_op(sent_rfq):
    client, headers, pid, org_id, rfq = sent_rfq
    rcp = rfq["recipients"][0]
    _deliver(client, "<v1@sup>", rcp["email"], "Total $52,000 delivered", thread="thr_1")
    _deliver(client, "<v2@sup>", rcp["email"], "Revised total $47,500 delivered", thread="thr_1")
    _deliver(client, "<v2@sup>", rcp["email"], "Revised total $47,500 delivered", thread="thr_1")
    rows = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert [r["total"] for r in rows] == ["$47,500"]
    db = SessionLocal()
    try:
        assert db.query(InboundEmail).count() == 2
    finally:
        db.close()


def test_dashboard_ingest_processes_rows_the_webhook_could_not(sent_rfq, monkeypatch):
    """Check for replies: a row stored while the handler was down (or that
    was reprocessed) is ingested by the project-level pass."""
    from app.services import inbound

    client, headers, pid, org_id, rfq = sent_rfq
    rcp = rfq["recipients"][0]
    monkeypatch.setattr(inbound, "handle", lambda db, row: None)  # webhook stores only
    _deliver(client, "<late@sup>", rcp["email"], "Total $8,000 delivered", thread="thr_1")
    row = _row("<late@sup>")
    assert row.kind == "unknown" and row.processed_at is None
    monkeypatch.undo()
    monkeypatch.setattr(intake, "attribute", lambda db, r: False)
    # Reprocess attributes it (kind + rfq) through the real dispatcher.
    r = client.post(f"/api/inbound/{row.id}/reprocess", headers=headers)
    assert r.status_code == 200
    assert _row("<late@sup>").kind == "rfq_reply"
    assert client.get(f"/api/projects/{pid}/quotes", headers=headers).json()[0]["total"] == "$8,000"

    # A second row attributed but left unprocessed is picked up by the
    # dashboard's ingest job (no mock quotes: real replies are on record).
    db = SessionLocal()
    try:
        db.add(InboundEmail(
            id="manual", organization_id=org_id, provider_message_id="<manual@sup>", inbox_id=INBOX,
            thread_id="thr_2", from_email=rfq["recipients"][1]["email"], subject="Re: RFQ",
            text="Total $7,000 delivered", attachments="[]", kind="rfq_reply",
            rfq_id=rfq["id"], project_id=pid,
        ))
        db.commit()
    finally:
        db.close()
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["status"] == "done" and st["mocked"] is False and st["ingested"] == 1, st
    totals = sorted(q["total"] for q in client.get(f"/api/projects/{pid}/quotes", headers=headers).json())
    assert totals == ["$7,000", "$8,000"]
    assert _row("<manual@sup>").processed_at is not None
