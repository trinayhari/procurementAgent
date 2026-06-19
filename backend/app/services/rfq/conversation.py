"""Build the email conversation for an RFQ (read-only).

Primary path uses the Gmail API: pull every message in each recipient's Gmail
thread — our outbound RFQ plus any supplier replies that threaded with it. When
Gmail isn't configured we fall back to a thread synthesised from what we already
store — the sent RFQ plus any ingested quotes — so the view still works offline.

Note: we deliberately read only the original thread. Automatic replies /
out-of-office acknowledgements arrive as a separate thread and are intentionally
not surfaced or acted on.
"""
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.repositories import quotes as quotes_repo
from app.services.quotes import gmail_reader
from app.services.rfq.sender import is_configured as gmail_configured
from app.services.rfq.sender import sender_address

logger = logging.getLogger("procureai.rfq.conversation")


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace("&", " ").split() if p]
    if not parts:
        return "SU"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _fmt_time(date_ms: int) -> str:
    if not date_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(date_ms / 1000)
    except (ValueError, OverflowError, OSError):
        return ""
    # e.g. "Jun 13, 2:30 PM" — strip a leading zero from the hour without %-I (portable).
    stamp = dt.strftime("%b %d, %I:%M %p")
    return stamp.replace(", 0", ", ")


def _money(v) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "—"


def build_conversation(db: Session, rfq: dict) -> dict:
    """Return {status, statusTone, gmail, thread} for an RFQ dict (rfqs_repo shape)."""
    if gmail_configured():
        emails = _gather_gmail(rfq)
        if emails:
            return {
                "status": rfq["status"],
                "statusTone": rfq["statusTone"],
                "gmail": True,
                "thread": _emails_to_thread(emails),
            }

    return {
        "status": rfq["status"],
        "statusTone": rfq["statusTone"],
        "gmail": False,
        "thread": _fallback_thread(db, rfq),
    }


def _gather_gmail(rfq: dict) -> Optional[List[gmail_reader.ThreadEmail]]:
    """Every message in this RFQ's Gmail thread(s), deduped + oldest-first.

    Reads only the thread our outbound landed in, so threaded supplier replies
    show up while separate-thread automatic replies stay out of scope.

    Returns None on a Gmail error (caller falls back), [] if nothing was found.
    """
    emails: List[gmail_reader.ThreadEmail] = []
    seen = set()
    try:
        for r in rfq.get("recipients", []):
            thread_id = r.get("threadId")
            if not thread_id:
                thread_id = gmail_reader.resolve_thread_id(r.get("sentMessageId") or "")
            if not thread_id:
                continue
            for e in gmail_reader.fetch_thread(thread_id):
                if e.message_id not in seen:
                    seen.add(e.message_id)
                    emails.append(e)
    except gmail_reader.GmailReadUnavailable as exc:
        logger.warning("Gmail conversation fetch failed: %s", exc)
        return None
    emails.sort(key=lambda e: e.date_ms)
    return emails


def _emails_to_thread(emails: List[gmail_reader.ThreadEmail]) -> List[dict]:
    our_addr = sender_address().lower()
    thread: List[dict] = []
    for i, e in enumerate(emails):
        is_out = e.from_email == our_addr
        who = "You · ProcureAI" if is_out else (e.from_name or e.from_email)
        thread.append({
            "dir": "out" if is_out else "in",
            "who": who,
            "initials": "YOU" if is_out else _initials(who),
            "time": _fmt_time(e.date_ms),
            # Only the opening message carries the subject line to avoid "Re:" noise.
            "subject": e.subject if i == 0 else None,
            "body": e.text or "",
            "attach": e.attachments[0] if e.attachments else None,
            "logoBg": None if is_out else "#334155",
        })
    return thread


def _fallback_thread(db: Session, rfq: dict) -> List[dict]:
    """Offline thread: the sent RFQ, plus any ingested quotes as inbound replies."""
    thread: List[dict] = [{
        "dir": "out",
        "who": "You · ProcureAI",
        "initials": "YOU",
        "time": "Sent" if rfq["status"] != "Draft" else "Draft",
        "subject": rfq.get("subject"),
        "body": rfq.get("body", ""),
        "attach": None,
        "logoBg": None,
    }]
    for q in quotes_repo.list_quotes(db, rfq["projectId"], rfq["package"]):
        if q.get("rfqId") and q["rfqId"] != rfq["id"]:
            continue
        name = q.get("supplierName") or q.get("supplierEmail") or "Supplier"
        body = (q.get("notes") or "").strip() or (
            f"Quote received — material {_money(q.get('materialCost'))}, "
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
