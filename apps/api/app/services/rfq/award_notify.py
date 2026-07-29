"""Notify suppliers of an award outcome, threaded into their RFQ conversation.

Winners receive a purchase-order confirmation listing the exact lines awarded to
them — in a split (mix-and-match) award each supplier sees only *their* lines,
with prices, freight, total and lead time. Suppliers who quoted but weren't
selected get a short "not selected this time" note. Every message replies inside
that supplier's original RFQ Gmail thread when we have its thread id, so the award
lands in the same conversation the RFQ went out on.

Uses the shared EmailSender, so with Gmail unconfigured it runs through MockSender
and the whole award→notify flow is exercisable offline.
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.repositories import quotes as quotes_repo
from app.repositories import rfqs as rfqs_repo
from app.services.quotes import gmail_reader
from app.services.rfq.sender import EmailSender, sender_address

logger = logging.getLogger("procureai.rfq.award_notify")


def _money(v) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"


def _sid(quote: dict) -> str:
    """The id compute_award keys a supplier by (mirrors line_comparison)."""
    return quote.get("supplierId") or quote.get("supplierName") or ""


def _signature(buyer) -> str:
    name = (getattr(buyer, "name", "") or "").strip()
    company = (getattr(buyer, "company", "") or "").strip()
    lines = [name or "The procurement team"]
    if company:
        lines.append(company)
    return "\n".join(lines)


def _winner_body(supplier: str, package_label: str, lines: List[dict],
                 subtotal: float, freight: float, total: float,
                 lead: Optional[int], buyer) -> str:
    items = []
    for i, li in enumerate(lines, 1):
        name = li.get("name") or "Item"
        qty = (li.get("qty") or "").strip()
        unit = li.get("unitPrice")
        ext = li.get("extended")
        lead_d = li.get("leadDays")
        piece = f"  {i}. {name}"
        if qty:
            piece += f" — {qty}"
        if unit is not None:
            piece += f" @ ${unit:,.2f}/unit"
        if ext is not None:
            piece += f" = {_money(ext)}"
        if lead_d is not None:
            piece += f"  ({lead_d}-day lead)"
        items.append(piece)

    lead_line = f"\nLead time: {lead} days" if lead is not None else ""
    return (
        f"Hi {supplier},\n\n"
        f"Thank you for your quote. We're issuing a purchase order for the "
        f"following {package_label} line item{'s' if len(lines) != 1 else ''} from "
        f"your bid:\n\n"
        + "\n".join(items)
        + "\n\n"
        f"Materials: {_money(subtotal)}\n"
        f"Freight:   {_money(freight)}\n"
        f"Total:     {_money(total)}"
        + lead_line
        + "\n\n"
        f"Please confirm receipt and reply with your order acknowledgement.\n\n"
        f"Thanks,\n{_signature(buyer)}"
    )


def _decline_body(supplier: str, package_label: str, buyer) -> str:
    return (
        f"Hi {supplier},\n\n"
        f"Thank you for quoting {package_label}. After comparing all bids we've "
        f"awarded this package to another supplier this time. We appreciate the "
        f"effort and will keep you in mind for upcoming work.\n\n"
        f"Thanks,\n{_signature(buyer)}"
    )


def _thread_ref(db: Session, org_id: str, quote: dict, sender: EmailSender):
    """(thread_id, in_reply_to, subject) for replying in this supplier's RFQ thread.

    thread_id comes straight off the stored RFQ recipient; the RFC822 Message-ID
    (for In-Reply-To) is fetched best-effort and only when Gmail is live.
    """
    rfq_id = quote.get("rfqId")
    if not rfq_id:
        return None, None, None
    rfq = rfqs_repo.get_rfq(db, org_id, rfq_id)
    if not rfq:
        return None, None, None
    email = (quote.get("supplierEmail") or "").strip().lower()
    recipient = next(
        (r for r in rfq.get("recipients", []) if (r.get("email") or "").strip().lower() == email),
        None,
    )
    if recipient is None:
        # We can't thread without the recipient's stored ids; use a plain subject.
        return None, None, None
    thread_id = recipient.get("threadId")
    in_reply_to = None
    if thread_id and not sender.mocked:
        try:
            in_reply_to = gmail_reader.rfc822_message_id(recipient.get("sentMessageId") or "")
        except Exception:  # pragma: no cover - best effort
            in_reply_to = None
    return thread_id, in_reply_to, rfq.get("subject")


def notify_award(
    db: Session,
    *,
    org_id: str,
    project_id: str,
    package: str,
    package_label: str,
    summary: dict,
    buyer,
    sender: EmailSender,
    notify_declined: bool = True,
) -> dict:
    """Email awarded (and optionally not-selected) suppliers for a package.

    Returns {notified, declined, failed, mock} — lists of per-supplier outcomes.
    Never raises: a per-supplier send failure is recorded and the rest proceed, so
    a flaky email never fails an award that is already committed.
    """
    quotes = quotes_repo.list_quotes(db, org_id, project_id, package)
    by_sid: Dict[str, dict] = {}
    for q in quotes:
        by_sid.setdefault(_sid(q), q)

    selections: Dict[str, str] = summary.get("selections") or {}
    winners = set(summary.get("supplierIds") or [])
    from_addr = (getattr(buyer, "sender_email", None) or sender_address())

    result = {"notified": [], "declined": [], "failed": [], "mock": bool(getattr(sender, "mocked", False))}

    def _send(quote, subject, body, kind):
        supplier = quote.get("supplierName") or quote.get("supplierEmail") or "Supplier"
        email = (quote.get("supplierEmail") or "").strip()
        if not email:
            result["failed"].append({"supplier": supplier, "email": None, "kind": kind,
                                      "error": "no email on file"})
            return
        thread_id, in_reply_to, rfq_subject = _thread_ref(db, org_id, quote, sender)
        subj = f"Re: {rfq_subject}" if rfq_subject else subject
        try:
            sender.send(email, subj, body, from_addr=from_addr,
                        thread_id=thread_id, in_reply_to=in_reply_to)
        except Exception as exc:
            logger.warning("Award %s email to %s failed: %s", kind, email, exc)
            result["failed"].append({"supplier": supplier, "email": email, "kind": kind,
                                     "error": str(exc)})
            return
        entry = {"supplier": supplier, "email": email, "threaded": bool(thread_id)}
        result["notified" if kind == "award" else "declined"].append(entry)

    # Winners — one email each, listing only the lines they won.
    for sid in winners:
        quote = by_sid.get(sid)
        if quote is None:
            continue
        won_names = [name for name, s in selections.items() if s == sid]
        lines = [li for li in quote.get("lineItems", []) if li.get("name") in set(won_names)]
        subtotal = round(sum(li["extended"] for li in lines if li.get("extended") is not None), 2)
        freight = quote.get("freight") or 0.0
        total = round(subtotal + freight, 2)
        leads = [li["leadDays"] for li in lines if li.get("leadDays") is not None]
        lead = max(leads) if leads else None
        supplier = quote.get("supplierName") or quote.get("supplierEmail") or "Supplier"
        body = _winner_body(supplier, package_label, lines, subtotal, freight, total, lead, buyer)
        _send(quote, f"Purchase order — {package_label}", body, "award")

    # Losers — suppliers who quoted this package but weren't selected.
    if notify_declined:
        for quote in quotes:
            if _sid(quote) in winners:
                continue
            supplier = quote.get("supplierName") or quote.get("supplierEmail") or "Supplier"
            body = _decline_body(supplier, package_label, buyer)
            _send(quote, f"{package_label} — sourcing update", body, "decline")

    return result
