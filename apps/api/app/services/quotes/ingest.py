"""Ingest supplier quote replies for a project.

Live path: every supplier reply arrives through the AgentMail webhook as an
`inbound_emails` row attributed to its RFQ (services/inbound/rfq_replies).
`ingest_inbound` parses ONE such row into structured terms and persists a
quote (deduped by the AgentMail message id); `ingest_quotes` runs it over the
rows a project has not processed yet, so the dashboard's "Check for replies"
still works. Mock path (no AgentMail key and no replies on record):
synthesize deterministic, comparable quotes for each recipient so the whole
quote→compare flow is exercisable offline, mirroring how sourcing/extraction
fall back to mocks.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.inbound_email import InboundEmail
from app.repositories import inbound_emails as inbound_repo
from app.repositories import quotes as quotes_repo
from app.repositories import rfqs as rfqs_repo
from app.services import storage
from app.services.email import text as email_text
from app.services.quotes import parser, pdf_text
from app.services.quotes.models import ParsedQuote
from app.services.rfq import state as rfq_state
from app.services.rfq.sender import is_configured

logger = logging.getLogger("procureai.quotes.ingest")

# Rough per-package material baseline (USD) for the offline mock.
_PKG_BASE = {"water": 490_000, "sewer": 215_000, "storm": 260_000, "erosion": 70_000}


@dataclass
class IngestOutcome:
    """What one ingest pass did. `ingested` counts new comparable quotes;
    `needs_review` counts replies stored without an amount; `superseded`
    counts earlier revisions replaced by a newer reply."""

    ingested: int = 0
    total: int = 0
    mocked: bool = False
    needs_review: int = 0
    superseded: int = 0
    skipped: List[str] = field(default_factory=list)  # message ids skipped, for logs/tests

    def __iter__(self):
        # Backwards-compatible unpacking: (ingested, total, mocked).
        return iter((self.ingested, self.total, self.mocked))


def _recipient_index(db: Session, org_id: str, project_id: str) -> Dict[str, List[dict]]:
    """email → [ {rfq_id, package, package_label, supplier_id, supplier_name,
    rfq_lines, thread_id, subject}, … ]: one entry per RFQ the supplier is on.

    A supplier is routinely asked to quote more than one package (water AND
    sewer). Keying on the first RFQ per email meant every reply from that
    supplier, whichever package it priced, was stored against one package
    and the other RFQ never left 'Awaiting'.
    """
    index: Dict[str, List[dict]] = {}
    for rfq in rfqs_repo.list_awaiting_rfqs(db, org_id, project_id):
        for r in rfq.get("recipients", []):
            email = (r.get("email") or "").strip().lower()
            if not email:
                continue
            if not rfq_state.recipient_sent(r):
                # Never received the RFQ (send failed / not attempted): any mail
                # from them is about something else.
                continue
            metas = index.setdefault(email, [])
            if any(m["rfq_id"] == rfq["id"] for m in metas):
                continue
            metas.append(recipient_meta(rfq, r))
    return index


def _match_rfq(metas: List[dict], msg) -> Optional[dict]:
    """Which of a supplier's RFQs a reply belongs to.

    In order: the thread the send created (a reply lands in it), then
    the RFQ subject quoted in the reply's subject ("Re: RFQ: Water …"), then
    and only when the supplier is on a single RFQ AND we have no thread to
    compare against (a send made before thread ids were stored, or a mock
    send), that one. When both sides have a thread id and they differ, the
    mail is about something else (another project's RFQ, a promo with a
    price in it) and is skipped rather than guessed.
    """
    if not metas:
        return None
    thread_id = getattr(msg, "thread_id", "") or ""
    if thread_id:
        for m in metas:
            if m["thread_id"] and m["thread_id"] == thread_id:
                return m
    subject = (getattr(msg, "subject", "") or "").strip().lower()
    if subject:
        hits = [m for m in metas if m["subject"] and m["subject"].strip().lower() in subject]
        if len(hits) == 1:
            return hits[0]
    if len(metas) == 1 and not (thread_id and metas[0].get("thread_id")):
        return metas[0]
    logger.warning(
        "Reply %s from %s could not be attributed to one of %d RFQs; skipped",
        getattr(msg, "message_id", "?"), getattr(msg, "from_email", "?"), len(metas),
    )
    return None


def _pair_count(index: Dict[str, List[dict]]) -> int:
    return sum(len(v) for v in index.values())


def ingest_quotes(db: Session, org_id: str, project_id: str) -> IngestOutcome:
    """Turn the project's unprocessed supplier replies into quotes. Unpacks as
    (ingested, total, mocked).

    Live whenever AgentMail is configured, and also when replies are already
    on record for the project (a webhook delivery forged locally with
    scripts/send_test_inbound.py): real replies never mix with mock quotes.
    """
    index = _recipient_index(db, org_id, project_id)
    total = _pair_count(index)
    if total == 0:
        return IngestOutcome(0, 0, not (is_configured() and parser.is_configured()))

    if is_configured() or inbound_repo.count_for_project(db, org_id, project_id):
        return _ingest_rows(db, org_id, project_id, index)
    return IngestOutcome(_ingest_mock(db, org_id, project_id, index), total, True)


def _has_amount(parsed: ParsedQuote) -> bool:
    """A quote we can rank (after finalize_quote): a total or a material
    subtotal. Unit prices without quantities don't add up to anything."""
    return parsed.total is not None or parsed.material_cost is not None


_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(name: str) -> set:
    return {t for t in _WORD_RE.findall((name or "").lower()) if len(t) > 1}


def fill_quantities_from_rfq(parsed: ParsedQuote, rfq_lines: Optional[List[dict]]) -> int:
    """Give a unit-priced line the quantity we asked for when the supplier
    didn't repeat it ("12\" DI pipe: $18.50/LF" answers our "2,400 LF" line).

    Matched by word overlap with the RFQ line names: the better of ≥60 % of
    the shorter name's words, or one name containing the other. Returns how
    many quantities were filled; finalize_quote() then totals them.
    """
    if not rfq_lines:
        return 0
    asked = []
    for item in rfq_lines:
        name = (item.get("n") or item.get("name") or "").strip()
        qty = (item.get("q") or item.get("qty") or "").strip()
        if name and qty and _qty_num(qty) is not None:
            asked.append((name, qty, _tokens(name)))
    filled = 0
    for li in parsed.line_items:
        if li.quantity and _qty_num(li.quantity) is not None:
            continue
        mine = _tokens(li.name)
        if not mine:
            continue
        best, best_score = None, 0.0
        for name, qty, theirs in asked:
            if not theirs:
                continue
            overlap = len(mine & theirs) / max(1, min(len(mine), len(theirs)))
            lo_a, lo_b = li.name.lower().strip(), name.lower().strip()
            if lo_a and (lo_a in lo_b or lo_b in lo_a):
                overlap = max(overlap, 1.0)
            if overlap > best_score:
                best, best_score = qty, overlap
        if best is not None and best_score >= 0.6:
            li.quantity = best
            filled += 1
    return filled


def recipient_meta(rfq: dict, recipient: dict) -> dict:
    """The per-RFQ context ingest_inbound needs, from an RFQ dict and one of
    its recipient dicts (same shape as _recipient_index entries)."""
    email = (recipient.get("email") or "").strip().lower()
    return {
        "email": email,
        "rfq_id": rfq["id"],
        "package": rfq["package"],
        "package_label": rfq.get("pkg") or rfq.get("packageLabel") or rfq["package"],
        "supplier_id": recipient.get("supplierId"),
        "supplier_name": recipient.get("name") or email,
        "rfq_lines": rfq.get("lineItems") or [],
        "thread_id": recipient.get("threadId") or "",
        "subject": rfq.get("subject") or "",
    }


def _attachment_text(msg: InboundEmail) -> List[str]:
    """Text layers of the PDF attachments stored for a received email."""
    import json

    out: List[str] = []
    try:
        attachments = json.loads(msg.attachments or "[]")
    except ValueError:
        return out
    for att in attachments:
        name = (att.get("filename") or "").lower()
        mime = (att.get("mimeType") or "").lower()
        locator = att.get("locator")
        if not locator or not (mime == "application/pdf" or name.endswith(".pdf")):
            continue
        try:
            with storage.local_copy(locator) as path:
                with open(path, "rb") as fh:
                    data = fh.read()
        except Exception:
            continue
        text = pdf_text.extract(data)
        if text:
            out.append(text)
    return out


def inbound_text(msg: InboundEmail) -> str:
    """What the supplier wrote in THIS message, plus the text of any PDF
    they attached.

    A reply carries the quoted chain beneath it (our RFQ, or their earlier
    quote); left in, the parser reads the old figures. AgentMail's
    `extracted_text` (stored as `text`) already drops the quoted history;
    strip_quoted() is a second pass for clients it misses, and an HTML-only
    body is rendered to text.
    """
    plain = (msg.text or "").strip()
    if not plain and msg.html:
        plain = email_text.html_to_text(msg.html)
    body = email_text.strip_quoted(plain) or plain
    return "\n\n".join([body, *_attachment_text(msg)]).strip()


def ingest_inbound(db: Session, org_id: str, project_id: str, rfq_meta: dict,
                   msg: InboundEmail) -> Optional[dict]:
    """Parse one supplier reply into a quote for the RFQ in `rfq_meta`.

    Returns the created quote dict, or None when the message is not a quote
    (a "received, will send Friday" note) or was already ingested. A real
    reply with nothing priced is stored as `needs_review` so the buyer sees
    it arrived. A revised quote from the same supplier supersedes the earlier
    one and the RFQ flips to Quoted once a rankable quote exists.
    """
    seen = quotes_repo.message_ids_for_project(db, org_id, project_id)
    if msg.provider_message_id in seen:
        return None
    parsed = parser.parse_quote(inbound_text(msg))
    if not parsed.is_quote:
        logger.info("Reply %s from %s is not a quote; skipped", msg.provider_message_id, msg.from_email)
        return None
    if fill_quantities_from_rfq(parsed, rfq_meta.get("rfq_lines")):
        note = "Quantities taken from the RFQ where the supplier priced per unit."
        parsed.notes = f"{parsed.notes}\n{note}".strip() if parsed.notes else note
    finalize_quote(parsed)
    if _has_amount(parsed):
        status = "received"
    else:
        # A real reply from a known supplier, but nothing priced in it (a
        # scan we couldn't read, a "see attached" with no attachment...).
        # Store it so the buyer sees it arrived, flagged for review; never
        # rank it.
        status = "needs_review"
        note = "No amount found in this reply: open the conversation and review it."
        parsed.notes = f"{parsed.notes}\n{note}".strip() if parsed.notes else note
    email = (msg.from_email or "").strip().lower()
    created = _persist(
        db, org_id, project_id, rfq_meta, parsed,
        source="agentmail", message_id=msg.provider_message_id, email=email, status=status,
    )
    created["superseded"] = quotes_repo.supersede_previous(
        db, org_id, project_id, rfq_meta["package"], email,
        rfq_id=rfq_meta["rfq_id"], supplier_id=rfq_meta.get("supplier_id"), keep_id=created.get("id"),
    )
    if status == "received" and rfq_meta.get("rfq_id"):
        rfqs_repo.mark_rfq_quoted(db, org_id, rfq_meta["rfq_id"])
    return created


def _meta_for_row(index: Dict[str, List[dict]], msg: InboundEmail) -> Optional[dict]:
    """The RFQ context for a row: on an attributed row, the recipient of that
    RFQ whose thread (then address) the reply matches; otherwise the sender's
    RFQs matched by thread / subject (_match_rfq)."""
    sender = (msg.from_email or "").strip().lower()
    if msg.rfq_id:
        on_rfq = [m for metas in index.values() for m in metas if m["rfq_id"] == msg.rfq_id]
        thread_id = (msg.thread_id or "").strip()
        for m in on_rfq:
            if thread_id and m["thread_id"] == thread_id:
                return m
        for m in on_rfq:
            if m["email"] == sender:
                return m
        if on_rfq:
            return on_rfq[0]
    return _match_rfq(index.get(sender) or [], msg)


def _ingest_rows(
    db: Session, org_id: str, project_id: str, index: Dict[str, List[dict]]
) -> IngestOutcome:
    outcome = IngestOutcome(total=_pair_count(index), mocked=False)
    # Oldest first so a later revision from the same supplier supersedes the
    # earlier one, never the other way round.
    for msg in inbound_repo.list_unprocessed_for_project(db, org_id, project_id):
        meta = _meta_for_row(index, msg)
        if meta is None:
            outcome.skipped.append(msg.provider_message_id)
            inbound_repo.mark_failed(db, msg, "No sent RFQ on this project matches the reply")
            continue
        try:
            created = ingest_inbound(db, org_id, project_id, meta, msg)
        except Exception as exc:
            logger.exception("Ingest of reply %s failed", msg.provider_message_id)
            inbound_repo.mark_failed(db, msg, str(exc) or exc.__class__.__name__)
            continue
        inbound_repo.mark_processed(db, msg)
        if created is None:
            outcome.skipped.append(msg.provider_message_id)
        elif created.get("status") == "received":
            outcome.ingested += 1
            outcome.superseded += created.get("superseded") or 0
        else:
            outcome.needs_review += 1
            outcome.superseded += created.get("superseded") or 0
    return outcome


def _ingest_mock(db: Session, org_id: str, project_id: str, index: Dict[str, List[dict]]) -> int:
    ingested = 0
    quoted_rfqs: set = set()
    for email, metas in index.items():
        for meta in metas:
            if quotes_repo.has_quote_for_recipient(db, org_id, project_id, meta["package"], email):
                continue
            parsed = _mock_quote(meta["supplier_name"], meta["package"], meta.get("rfq_lines"))
            _persist(db, org_id, project_id, meta, parsed, source="mock", message_id=None, email=email)
            ingested += 1
            if meta["rfq_id"]:
                quoted_rfqs.add(meta["rfq_id"])
    for rfq_id in quoted_rfqs:
        rfqs_repo.mark_rfq_quoted(db, org_id, rfq_id)
    return ingested


def _persist(db, org_id, project_id, meta, parsed, *, source, message_id, email=None,
             status: str = "received") -> dict:
    # Normalize parsed lines into the shape the comparison engine reads
    # ({name, qty, unitPrice, extended, leadDays}, see line_comparison.py).
    line_items = [
        {
            "name": li.name,
            "qty": li.quantity or "",
            "unitPrice": li.unit_price,
            "extended": li.extended,
            "leadDays": li.lead_days if li.lead_days is not None else parsed.lead_days,
        }
        for li in parsed.line_items
        if li.name
    ]
    return quotes_repo.create_quote(
        db,
        org_id,
        project_id=project_id,
        package=meta["package"],
        package_label=meta["package_label"],
        rfq_id=meta["rfq_id"],
        supplier_id=meta["supplier_id"],
        supplier_name=parsed.supplier_name or meta["supplier_name"],
        supplier_email=email,
        material_cost=parsed.material_cost,
        freight=parsed.freight,
        total=parsed.total,
        lead_days=parsed.lead_days,
        delivery_date=parsed.delivery_date,
        validity=parsed.validity,
        line_items=line_items,
        notes=parsed.notes or "",
        source=source,
        source_message_id=message_id,
        status=status,
    )


_QTY_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def _qty_num(qty: str) -> Optional[float]:
    """First number in a quantity string ('1,682.7 LF' → 1682.7)."""
    m = _QTY_RE.search(qty or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def finalize_quote(parsed: ParsedQuote) -> ParsedQuote:
    """Fill the line and header figures a supplier priced but didn't total up.

    Suppliers routinely reply with unit prices and no material subtotal or grand
    total, yet the comparison engine needs both a per-line `extended` and header
    totals to rank a quote (line_comparison.py drops any line missing `extended`).
    We derive those deterministically here, never in the LLM prompt, whose
    arithmetic was observed to drift by ~$1, so a unit-priced reply is comparable:

      - per-line extended = unit_price × quantity  (recomputed in code whenever the
        quantity is numeric; a supplier-stated extended is kept only when we can't
        parse the quantity, e.g. "TBD")
      - material_cost = Σ line extendeds        (only when the supplier omitted it)
      - total = material_cost + freight         (only when the supplier omitted it)
      - lead_days = longest per-line lead        (only when no header lead was given)

    Mutates and returns `parsed`. Any header figure we compute is flagged in
    `notes` so the UI can tell computed values from supplier-stated ones.
    """
    for li in parsed.line_items:
        qty_num = _qty_num(li.quantity or "")
        if li.unit_price is not None and qty_num is not None:
            li.extended = round(li.unit_price * qty_num, 2)  # trust code over LLM math

    derived: List[str] = []

    line_exts = [li.extended for li in parsed.line_items if li.extended is not None]
    if parsed.material_cost is None and line_exts:
        parsed.material_cost = round(sum(line_exts), 2)
        derived.append("material subtotal")

    if parsed.total is None and parsed.material_cost is not None:
        parsed.total = round(parsed.material_cost + (parsed.freight or 0.0), 2)
        derived.append("total")
    elif parsed.material_cost is None and parsed.total is not None and parsed.freight is not None:
        parsed.material_cost = round(parsed.total - parsed.freight, 2)
        derived.append("material subtotal")

    if parsed.lead_days is None:
        line_leads = [li.lead_days for li in parsed.line_items if li.lead_days is not None]
        if line_leads:
            parsed.lead_days = max(line_leads)
            derived.append("lead time")

    if derived:
        tag = "Computed from line items: " + ", ".join(dict.fromkeys(derived)) + "."
        parsed.notes = f"{parsed.notes}\n{tag}".strip() if parsed.notes else tag

    return parsed


def _mock_quote(supplier_name: str, package: str, rfq_lines: Optional[List[dict]] = None):
    """Deterministic, plausible quote derived from the supplier name + package.

    When the RFQ's line items are available, each is priced per-line (unit price
    varies per supplier) so the line-by-line comparison and award strategies are
    fully exercisable offline; otherwise fall back to a package-level baseline.
    """
    from app.services.quotes.models import ParsedQuote, ParsedQuoteLine

    h = sum(ord(c) for c in (supplier_name or "x"))
    lead = 10 + (h % 20)  # 10–29 days

    lines: List[ParsedQuoteLine] = []
    material = 0.0
    for item in rfq_lines or []:
        name = (item.get("n") or item.get("name") or "").strip()
        if not name:
            continue
        qty = item.get("q") or ""
        qty_num = _qty_num(qty) or 1.0
        hh = h + sum(ord(c) for c in name)
        unit = round(18.0 + (hh % 900) * (0.85 + (h % 30) / 100.0), 2)  # per-supplier spread
        extended = round(unit * qty_num, 2)
        material += extended
        lines.append(ParsedQuoteLine(name=name, quantity=qty, unit_price=unit, extended=extended))

    if lines:
        material = round(material, 2)
        freight = round(max(material, 10_000) * (0.012 + (h % 7) / 1000.0), 2)
    else:
        base = _PKG_BASE.get(package, 200_000)
        spread = 0.88 + (h % 25) / 100.0  # 0.88–1.12 of baseline
        material = round(base * spread, -2)
        freight = round(base * (0.012 + (h % 7) / 1000.0), -2)
    total = round(material + freight, 2)
    return ParsedQuote(
        is_quote=True,
        supplier_name=supplier_name,
        material_cost=material,
        freight=freight,
        total=total,
        lead_days=lead,
        validity="30 days",
        line_items=lines,
        notes="Simulated quote (set the AgentMail + OpenAI keys for live ingest).",
    )
