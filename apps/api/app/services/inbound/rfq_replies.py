"""Supplier replies to RFQs.

attribute(): the received email's AgentMail `thread_id` matches the `threadId`
recorded on an RFQ recipient when the RFQ was sent (fallback: its In-Reply-To
names the `messageId` we sent). Sets msg.rfq_id / project_id and returns True.

handle(): stamps `repliedAt` on that recipient, parses the message into a
quote (services/quotes/ingest.ingest_inbound) and marks the row processed, or
records the error so it can be re-run from POST /api/inbound/{id}/reprocess.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.inbound_email import InboundEmail
from app.models.rfq import Rfq
from app.repositories import inbound_emails as inbound_repo
from app.repositories import rfqs as rfqs_repo
from app.services.quotes import ingest as quotes_ingest
from app.services.rfq import state as rfq_state

logger = logging.getLogger("procureai.inbound.rfq_replies")


def _recipient_ids(recipient: dict) -> set:
    """Every id we may have recorded for the message we sent this recipient
    (`messageId` today, `sentMessageId` for rows written before it existed),
    plus any award / follow-up notice sent in the same thread."""
    ids = {
        str(recipient.get("messageId") or ""),
        str(recipient.get("sentMessageId") or ""),
    }
    ids.update(str(x) for x in (recipient.get("outboundMessageIds") or []) if x)
    for f in recipient.get("followups") or []:
        if isinstance(f, dict) and f.get("messageId"):
            ids.add(str(f["messageId"]))
    return {i for i in ids if i and not i.startswith(("error", "mock"))}


def _find_recipient(db: Session, org_id: Optional[str], msg: InboundEmail) -> Tuple[Optional[Rfq], Optional[dict]]:
    """(rfq row, recipient dict) whose sent RFQ this message replies to.

    Only RFQs of the organization that owns the inbox are candidates: the
    webhook sets `organization_id` from `inbox_id` before attribution runs.
    """
    thread_id = (msg.thread_id or "").strip()
    in_reply_to = (msg.in_reply_to or "").strip()
    if not org_id or (not thread_id and not in_reply_to):
        return None, None
    stmt = select(Rfq).where(
        Rfq.organization_id == org_id,
        Rfq.status.in_(["Sent", "Awaiting", "Send failed", "Quoted"]),
    )
    # Two passes so a thread match always wins over an In-Reply-To match.
    rows = db.scalars(stmt).all()
    by_reply: Tuple[Optional[Rfq], Optional[dict]] = (None, None)
    for rfq in rows:
        try:
            recipients = json.loads(rfq.recipients or "[]")
        except ValueError:
            continue
        for r in recipients:
            if not rfq_state.recipient_sent(r):
                continue
            rid = str(r.get("threadId") or "")
            if thread_id and rid and rid == thread_id and not rid.startswith("mock"):
                return rfq, r
            if in_reply_to and by_reply[0] is None and in_reply_to in _recipient_ids(r):
                by_reply = (rfq, r)
    return by_reply


def attribute(db: Session, msg: InboundEmail) -> bool:
    rfq, recipient = _find_recipient(db, msg.organization_id, msg)
    if rfq is None:
        return False
    msg.rfq_id = rfq.id
    msg.project_id = rfq.project_id
    return True


def _mark_replied(db: Session, org_id: str, rfq_id: str, recipient_email: str,
                  when: datetime) -> None:
    rfq = rfqs_repo.get_rfq(db, org_id, rfq_id)
    if rfq is None:
        return
    recipients = rfq.get("recipients") or []
    email = (recipient_email or "").strip().lower()
    changed = False
    for r in recipients:
        if (r.get("email") or "").strip().lower() == email and not r.get("repliedAt"):
            r["repliedAt"] = when.isoformat()
            changed = True
    if changed:
        rfqs_repo.save_recipients(db, org_id, rfq_id, recipients)


def handle(db: Session, msg: InboundEmail) -> None:
    if msg.processed_at is not None:
        return
    org_id = msg.organization_id
    rfq, recipient = _find_recipient(db, org_id, msg)
    if rfq is None or recipient is None or not org_id:
        inbound_repo.mark_failed(db, msg, "Reply no longer matches a sent RFQ")
        return
    when = msg.received_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        _mark_replied(db, org_id, rfq.id, recipient.get("email") or "", when)
        rfq_dict = rfqs_repo.get_rfq(db, org_id, rfq.id) or rfq.to_dict()
        meta = quotes_ingest.recipient_meta(rfq_dict, recipient)
        quote = quotes_ingest.ingest_inbound(db, org_id, rfq.project_id, meta, msg)
    except Exception as exc:
        logger.exception("Supplier reply %s could not be processed", msg.id)
        inbound_repo.mark_failed(db, msg, str(exc) or exc.__class__.__name__)
        return
    inbound_repo.mark_processed(db, msg)
    if quote is not None:
        logger.info(
            "Supplier reply %s from %s stored as quote %s (%s)",
            msg.id, msg.from_email, quote.get("id"), quote.get("status"),
        )
