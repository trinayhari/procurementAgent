"""Notify suppliers of an award outcome, threaded into their RFQ conversation.

Winners receive a purchase-order confirmation listing the exact lines awarded to
them; in a split (mix-and-match) award each supplier sees only *their* lines,
with prices, freight, total and lead time. Suppliers who quoted but weren't
selected get a short "not selected this time" note. Every message is sent as a
reply to the RFQ we sent that supplier (its recorded AgentMail message id), so
the award lands in the same conversation the RFQ went out on.

Uses the shared EmailSender, so with AgentMail unconfigured it runs through
MockSender and the whole award→notify flow is exercisable offline.
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.repositories import quotes as quotes_repo
from app.repositories import rfqs as rfqs_repo
from app.services.rfq.sender import EmailSender, from_header

logger = logging.getLogger("procureai.rfq.award_notify")


def _money(v) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "-"


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
                 lead: Optional[int], buyer, po: Optional[str] = None) -> str:
    items = []
    for i, li in enumerate(lines, 1):
        name = li.get("name") or "Item"
        qty = (li.get("qty") or "").strip()
        unit = li.get("unitPrice")
        ext = li.get("extended")
        lead_d = li.get("leadDays")
        piece = f"  {i}. {name}"
        if qty:
            piece += f", {qty}"
        if unit is not None:
            piece += f" @ ${unit:,.2f}/unit"
        if ext is not None:
            piece += f" = {_money(ext)}"
        if lead_d is not None:
            piece += f"  ({lead_d}-day lead)"
        items.append(piece)

    lead_line = f"\nLead time: {lead} days" if lead is not None else ""
    po_ref = f" ({po})" if po else ""
    po_line = f"PO number: {po}\n" if po else ""
    return (
        f"Hi {supplier},\n\n"
        f"Thank you for your quote. We're issuing a purchase order{po_ref} for the "
        f"following {package_label} line item{'s' if len(lines) != 1 else ''} from "
        f"your bid:\n\n"
        + "\n".join(items)
        + "\n\n"
        + po_line
        + f"Materials: {_money(subtotal)}\n"
        f"Freight:   {_money(freight)}\n"
        f"Total:     {_money(total)}"
        + lead_line
        + "\n\n"
        f"Please confirm receipt and reply with your order acknowledgement.\n\n"
        f"Thanks,\n{_signature(buyer)}"
    )


def _withdrawn_body(supplier: str, package_label: str, previous: dict, buyer) -> str:
    """For a supplier whose earlier PO is cancelled by a re-award."""
    when = (previous.get("createdAt") or "")[:10]
    total = previous.get("total")
    ref = f" issued on {when}" if when else ""
    amount = f" ({_money(total)})" if isinstance(total, (int, float)) and previous.get("poCount") == 1 else ""
    return (
        f"Hi {supplier},\n\n"
        f"Please disregard the purchase order for {package_label}{ref}{amount}: after "
        f"revisiting the bids we have re-awarded this package and that order is "
        f"withdrawn. Do not ship or invoice against it.\n\n"
        f"We're sorry for the change of plan and appreciate your quote; we'll keep "
        f"you in mind for upcoming work.\n\n"
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

    Both ids come straight off the stored RFQ recipient: `threadId` and the
    `messageId` of the RFQ we sent (`sentMessageId` on rows written before
    that key existed). The sender turns `in_reply_to` into messages.reply.
    """
    rfq_id = quote.get("rfqId")
    if not rfq_id:
        return None, None, None
    rfq = rfqs_repo.get_rfq(db, org_id, rfq_id)
    if not rfq:
        return None, None, None
    email = (quote.get("supplierEmail") or "").strip().lower()
    sid = quote.get("supplierId")
    recipients = rfq.get("recipients", [])
    recipient = next(
        (r for r in recipients if (r.get("email") or "").strip().lower() == email),
        None,
    )
    if recipient is None and sid:
        # The quote came back from a different address than the one we
        # emailed (RFQ to sales@, reply from the estimator): still the same
        # supplier record, so reply in that thread.
        recipient = next((r for r in recipients if r.get("supplierId") == sid), None)
    if recipient is None:
        # We can't thread without the recipient's stored ids; use a plain subject.
        return None, None, None
    thread_id = recipient.get("threadId")
    in_reply_to = recipient.get("messageId") or recipient.get("sentMessageId") or None
    if in_reply_to and str(in_reply_to).startswith(("mock", "error")):
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
    only_emails: Optional[set] = None,
    superseded: Optional[dict] = None,
    po_numbers: Optional[List[dict]] = None,
) -> dict:
    """Email awarded (and optionally not-selected) suppliers for a package.

    Returns {notified, declined, failed, mock}: lists of per-supplier outcomes.
    Never raises: a per-supplier send failure is recorded and the rest proceed, so
    a flaky email never fails an award that is already committed.

    `only_emails` restricts the run to those supplier addresses, used to
    re-send just the notifications that failed the first time.

    `superseded` is the earlier purchase decision a re-award replaces: its
    winners who are no longer winning get a PO-withdrawn notice (naming the
    earlier order) instead of the generic "not selected" note.

    `po_numbers` ([{supplierId, supplierName, po}], from the purchase decision)
    puts each winner's PO number in their confirmation.
    """
    po_by_sid = {p.get("supplierId"): p.get("po") for p in (po_numbers or []) if p.get("po")}
    quotes = quotes_repo.list_quotes(db, org_id, project_id, package)
    by_sid: Dict[str, dict] = {}
    for q in quotes:
        by_sid.setdefault(_sid(q), q)

    selections: Dict[str, str] = summary.get("selections") or {}
    winners = set(summary.get("supplierIds") or [])
    # Always the org's agent inbox, with the buyer's name/company as the display
    # name; the buyer's own address rides along as a Cc.
    from_addr = from_header(buyer, address=getattr(sender, "address", None))
    cc = getattr(buyer, "cc_email", None)

    result = {"notified": [], "declined": [], "withdrawn": [], "failed": [],
              "mock": bool(getattr(sender, "mocked", False))}
    previous_winners = set((superseded or {}).get("supplierIds") or [])

    wanted = {e.strip().lower() for e in (only_emails or set()) if e}

    def _send(quote, subject, body, kind):
        supplier = quote.get("supplierName") or quote.get("supplierEmail") or "Supplier"
        email = (quote.get("supplierEmail") or "").strip()
        if wanted and email.lower() not in wanted:
            return
        if not email:
            result["failed"].append({"supplier": supplier, "email": None, "kind": kind,
                                      "error": "no email on file"})
            return
        thread_id, in_reply_to, rfq_subject = _thread_ref(db, org_id, quote, sender)
        subj = f"Re: {rfq_subject}" if rfq_subject else subject
        try:
            sent = sender.send(email, subj, body, from_addr=from_addr, cc=cc,
                               thread_id=thread_id, in_reply_to=in_reply_to)
        except Exception as exc:
            logger.warning("Award %s email to %s failed: %s", kind, email, exc)
            result["failed"].append({"supplier": supplier, "email": email, "kind": kind,
                                     "error": str(exc) or exc.__class__.__name__})
            return
        # Remember our own message id so a supplier reply to this notice still
        # attributes to the RFQ (In-Reply-To fallback) and ingest never reads
        # the notice back as a supplier reply.
        if quote.get("rfqId") and getattr(sent, "message_id", ""):
            try:
                rfqs_repo.record_outbound_message(
                    db, org_id, quote["rfqId"], email, sent.message_id
                )
            except Exception:  # pragma: no cover - bookkeeping must not fail the award
                logger.exception("Could not record outbound message id for %s", email)
        entry = {"supplier": supplier, "email": email, "threaded": bool(thread_id)}
        result[{"award": "notified", "decline": "declined", "withdrawn": "withdrawn"}[kind]].append(entry)

    # Winners: one email each, listing only the lines they won.
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
        po = po_by_sid.get(sid)
        body = _winner_body(supplier, package_label, lines, subtotal, freight, total, lead, buyer, po=po)
        subject = f"Purchase order {po}: {package_label}" if po else f"Purchase order: {package_label}"
        _send(quote, subject, body, "award")

    # Losers: suppliers who quoted this package but weren't selected. One
    # note per supplier (list_quotes already hides superseded revisions and
    # amount-less replies, and by_sid collapses any remaining duplicates).
    if notify_declined:
        for sid, quote in by_sid.items():
            if sid in winners:
                continue
            supplier = quote.get("supplierName") or quote.get("supplierEmail") or "Supplier"
            if sid in previous_winners:
                # Their PO from the earlier award is being cancelled: say so.
                body = _withdrawn_body(supplier, package_label, superseded or {}, buyer)
                _send(quote, f"{package_label}: purchase order withdrawn", body, "withdrawn")
                continue
            body = _decline_body(supplier, package_label, buyer)
            _send(quote, f"{package_label}: sourcing update", body, "decline")

    return result
