"""Build the email conversation for an RFQ (read-only).

The thread is assembled from what we store: the RFQ we sent (one bubble per
send) followed by every supplier reply the agent inbox received for this RFQ
(`inbound_emails` rows attributed by thread id), oldest first. No API call on
the read path: the AgentMail webhook already delivered every message, so the
view is fast and works offline. Before AgentMail is configured (mock sends)
the same shape is built from the stored RFQ plus any ingested quotes.

Note: only replies in the thread our outbound created are attributed here.
Automatic replies / out-of-office acknowledgements arrive as a separate
thread and are intentionally not surfaced or acted on.
"""
import json
import logging
from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.inbound_email import InboundEmail
from app.models.user import User
from app.repositories import inbound_emails as inbound_repo
from app.repositories import quotes as quotes_repo
from app.services.email import text as email_text
from app.services.rfq import state as rfq_state
from app.services.rfq.sender import is_configured, sender_address

logger = logging.getLogger("procureai.rfq.conversation")


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace("&", " ").split() if p]
    if not parts:
        return "SU"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _fmt_time(when) -> str:
    """'Jun 13, 2:30 PM' from a datetime or epoch milliseconds ('' when unset)."""
    if not when:
        return ""
    try:
        dt = when if isinstance(when, datetime) else datetime.fromtimestamp(when / 1000)
    except (ValueError, OverflowError, OSError, TypeError):
        return ""
    # Strip a leading zero from the hour without %-I (portable).
    stamp = dt.strftime("%b %d, %I:%M %p")
    return stamp.replace(", 0", ", ")


def _money(v) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "-"


def build_conversation(db: Session, org_id: str, rfq: dict) -> dict:
    """Return {status, statusTone, live, configured, thread} for an RFQ dict
    (rfqs_repo shape).

    `live` is True when the thread includes replies received by the agent
    inbox; otherwise it is the stored RFQ plus any ingested quotes rendered as
    replies (mock sends), and the UI says so.
    """
    replies = inbound_repo.list_for_rfq(db, org_id, rfq["id"])
    if replies:
        thread = _outbound_bubbles(rfq) + _replies_to_thread(replies, _known_sender_addrs(db, org_id))
    else:
        thread = _fallback_thread(db, org_id, rfq)
    return {
        "status": rfq["status"],
        "statusTone": rfq["statusTone"],
        "live": bool(replies),
        "configured": is_configured(),
        "thread": thread,
    }


def _known_sender_addrs(db: Session, org_id: str) -> set:
    """Every address this org's mail may come from, for telling our own
    messages apart from supplier replies in a thread.

    The agent inbox sends everything. Members' login and Cc addresses are
    included too: a teammate who answers the supplier from their own mailbox
    (Cc'd on the RFQ) is still "us"."""
    addrs = {sender_address(db, org_id).lower()}
    for email, cc in db.execute(
        select(User.email, User.cc_email).where(User.organization_id == org_id)
    ):
        if email:
            addrs.add(email.strip().lower())
        if cc:
            addrs.add(cc.strip().lower())
    return addrs


def _reply_body(row: InboundEmail) -> str:
    plain = (row.text or "").strip()
    if not plain and row.html:
        plain = email_text.html_to_text(row.html)
    return email_text.strip_quoted(plain) or plain


def _attachment_names(row: InboundEmail) -> List[str]:
    try:
        return [a.get("filename") for a in json.loads(row.attachments or "[]") if a.get("filename")]
    except ValueError:
        return []


def _replies_to_thread(rows: List[InboundEmail], our_addrs: set) -> List[dict]:
    thread: List[dict] = []
    for row in rows:
        is_out = (row.from_email or "").lower() in our_addrs
        who = "You · Proq" if is_out else (row.from_name or row.from_email)
        files = _attachment_names(row)
        thread.append({
            "dir": "out" if is_out else "in",
            "who": who,
            "initials": "YOU" if is_out else _initials(who),
            "time": _fmt_time(row.received_at),
            # The opening message carries the subject line; replies don't, to
            # avoid "Re:" noise.
            "subject": None,
            "body": _reply_body(row),
            "attach": files[0] if files else None,
            "logoBg": None if is_out else "#334155",
        })
    return thread


def _outbound_label(rfq: dict) -> str:
    """What happened to our message, from the per-recipient send record,
    never "Sent" for an RFQ nobody received."""
    if rfq.get("status") == "Draft":
        return "Draft"
    recipients = rfq.get("recipients") or []
    delivered = [r for r in recipients if rfq_state.recipient_sent(r)]
    if recipients and not delivered:
        return "Not delivered"
    if delivered and all(r.get("mock") for r in delivered):
        return "Logged only (mock, not delivered)"
    if len(delivered) < len(recipients):
        return f"Sent to {len(delivered)} of {len(recipients)}"
    return "Sent"


def _outbound_bubbles(rfq: dict) -> List[dict]:
    """The RFQ as we sent it: one bubble, timed by the send."""
    sent_at = None
    for r in rfq.get("recipients") or []:
        if r.get("sentAt"):
            try:
                sent_at = datetime.fromisoformat(str(r["sentAt"]).replace("Z", "+00:00"))
            except ValueError:
                sent_at = None
            if sent_at is not None:
                break
    return [{
        "dir": "out",
        "who": "You · Proq",
        "initials": "YOU",
        "time": _fmt_time(sent_at) or _outbound_label(rfq),
        "subject": rfq.get("subject"),
        "body": rfq.get("body", ""),
        "attach": None,
        "logoBg": None,
    }]


def _fallback_thread(db: Session, org_id: str, rfq: dict) -> List[dict]:
    """Offline thread: the sent RFQ, plus any ingested quotes as inbound replies."""
    thread: List[dict] = [{
        "dir": "out",
        "who": "You · Proq",
        "initials": "YOU",
        "time": _outbound_label(rfq),
        "subject": rfq.get("subject"),
        "body": rfq.get("body", ""),
        "attach": None,
        "logoBg": None,
    }]
    for q in quotes_repo.list_quotes(db, org_id, rfq["projectId"], rfq["package"]):
        if q.get("rfqId") and q["rfqId"] != rfq["id"]:
            continue
        name = q.get("supplierName") or q.get("supplierEmail") or "Supplier"
        body = (q.get("notes") or "").strip() or (
            f"Quote received: material {_money(q.get('materialCost'))}, "
            f"freight {_money(q.get('freight'))}, total {_money(q.get('total'))}"
            + (f", {q['leadDays']}-day lead" if q.get("leadDays") is not None else "")
        )
        thread.append({
            "dir": "in",
            "who": name,
            "initials": _initials(name),
            "time": "Reply",
            "subject": None,
            "body": body,
            "attach": None,
            "logoBg": "#334155",
        })
    return thread
