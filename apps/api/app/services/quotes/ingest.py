"""Ingest supplier quote replies for a project.

Live path: read Gmail replies from the RFQ recipients, parse each into structured
terms, and persist one quote per supplier (deduped by Gmail message id). Mock path
(no Gmail/OpenAI creds): synthesize deterministic, comparable quotes for each
recipient so the whole quote→compare flow is exercisable offline — mirroring how
sourcing/extraction fall back to mocks.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.repositories import quotes as quotes_repo
from app.repositories import rfqs as rfqs_repo
from app.services.quotes import gmail_reader, parser
from app.services.quotes.models import ParsedQuote
from app.services.rfq import state as rfq_state
from app.services.rfq.sender import is_configured as gmail_configured

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


def _outbound_message_ids(db: Session, org_id: str, project_id: str) -> Set[str]:
    """Gmail ids of every message *we* sent for this project's RFQs — the RFQ
    itself and any award/decline notice threaded on it. Needed because a
    loop-back setup (supplier address == the workspace mailbox, as in a live
    test) makes our own outbound match the `from:` query."""
    ids: Set[str] = set()
    for rfq in rfqs_repo.list_awaiting_rfqs(db, org_id, project_id):
        for r in rfq.get("recipients", []):
            mid = str(r.get("sentMessageId") or "")
            if mid and not mid.startswith("error"):
                ids.add(mid)
            for extra in r.get("outboundMessageIds") or []:
                if extra:
                    ids.add(str(extra))
    return ids


def _recipient_index(db: Session, org_id: str, project_id: str) -> Dict[str, List[dict]]:
    """email → [ {rfq_id, package, package_label, supplier_id, supplier_name,
    rfq_lines, thread_id, subject}, … ] — one entry per RFQ the supplier is on.

    A supplier is routinely asked to quote more than one package (water AND
    sewer). Keying on the first RFQ per email meant every reply from that
    supplier — whichever package it priced — was stored against one package
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
            metas.append(
                {
                    "rfq_id": rfq["id"],
                    "package": rfq["package"],
                    "package_label": rfq.get("pkg") or rfq["package"],
                    "supplier_id": r.get("supplierId"),
                    "supplier_name": r.get("name") or email,
                    "rfq_lines": rfq.get("lineItems") or [],
                    "thread_id": r.get("threadId") or "",
                    "subject": rfq.get("subject") or "",
                }
            )
    return index


def _match_rfq(metas: List[dict], msg) -> Optional[dict]:
    """Which of a supplier's RFQs a reply belongs to.

    In order: the Gmail thread the send created (a reply lands in it), then
    the RFQ subject quoted in the reply's subject ("Re: RFQ: Water …"), then
    — only when the supplier is on a single RFQ AND we have no thread to
    compare against (a send made before thread ids were stored, or a mock
    send) — that one. When both sides have a thread id and they differ, the
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
    """Read supplier replies and store them as quotes. Unpacks as (ingested, total, mocked)."""
    index = _recipient_index(db, org_id, project_id)
    total = _pair_count(index)
    if total == 0:
        return IngestOutcome(0, 0, not (gmail_configured() and parser.is_configured()))

    if gmail_configured():
        return _ingest_live(db, org_id, project_id, index)
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

    Matched by word overlap with the RFQ line names — the better of ≥60 % of
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


def _ingest_live(
    db: Session, org_id: str, project_id: str, index: Dict[str, List[dict]]
) -> IngestOutcome:
    # Idempotent re-runs: every Gmail message id we've stored a quote for is
    # skipped, as is every message we sent ourselves.
    seen = quotes_repo.message_ids_for_project(db, org_id, project_id)
    ours = _outbound_message_ids(db, org_id, project_id)
    our_addrs = _our_addresses(db, org_id)
    try:
        candidates = _collect_replies(index, our_addrs, skip_ids=seen | ours)
    except gmail_reader.GmailReadUnavailable as exc:
        logger.warning("Gmail read unavailable: %s", exc)
        raise

    outcome = IngestOutcome(total=_pair_count(index), mocked=False)
    quoted_rfqs: set = set()
    # Oldest first so a later revision from the same supplier supersedes the
    # earlier one, never the other way round.
    for msg, meta in sorted(candidates, key=lambda pair: getattr(pair[0], "date_ms", 0) or 0):
        if msg.message_id in seen or msg.message_id in ours:
            outcome.skipped.append(msg.message_id)
            continue
        if meta is None:
            meta = _match_rfq(index.get(msg.from_email) or [], msg)
        if meta is None:
            outcome.skipped.append(msg.message_id)
            continue
        parsed = parser.parse_quote(msg.combined_text)
        if not parsed.is_quote:
            logger.info("Reply %s from %s is not a quote; skipped", msg.message_id, msg.from_email)
            outcome.skipped.append(msg.message_id)
            continue
        if fill_quantities_from_rfq(parsed, meta.get("rfq_lines")):
            note = "Quantities taken from the RFQ where the supplier priced per unit."
            parsed.notes = f"{parsed.notes}\n{note}".strip() if parsed.notes else note
        finalize_quote(parsed)
        if _has_amount(parsed):
            status = "received"
        else:
            # A real reply from a known supplier, but nothing priced in it (a
            # scan we couldn't read, a "see attached" with no attachment…).
            # Store it so the buyer sees it arrived, flagged for review; never
            # rank it.
            status = "needs_review"
            note = "No amount found in this reply — open the conversation and review it."
            parsed.notes = f"{parsed.notes}\n{note}".strip() if parsed.notes else note
        created = _persist(
            db, org_id, project_id, meta, parsed,
            source="gmail", message_id=msg.message_id, email=msg.from_email, status=status,
        )
        outcome.superseded += quotes_repo.supersede_previous(
            db, org_id, project_id, meta["package"], msg.from_email,
            rfq_id=meta["rfq_id"], supplier_id=meta.get("supplier_id"), keep_id=created.get("id"),
        )
        seen.add(msg.message_id)
        if status == "received":
            outcome.ingested += 1
            if meta["rfq_id"]:
                quoted_rfqs.add(meta["rfq_id"])
        else:
            outcome.needs_review += 1

    for rfq_id in quoted_rfqs:
        rfqs_repo.mark_rfq_quoted(db, org_id, rfq_id)
    return outcome


def _our_addresses(db: Session, org_id: str) -> set:
    """The workspace mailbox plus this org's members' login and Cc addresses —
    messages from any of them in an RFQ thread are ours, not a supplier's."""
    from app.services.rfq.conversation import _known_sender_addrs

    try:
        return _known_sender_addrs(db, org_id)
    except Exception:  # pragma: no cover - defensive; never block ingest on this
        from app.services.rfq.sender import sender_address

        return {sender_address().lower()}


def _collect_replies(index: Dict[str, List[dict]], our_addrs: set,
                     skip_ids: Optional[set] = None) -> List[tuple]:
    """(message, meta-or-None) pairs worth parsing, deduped by Gmail id.

    Two sources, in priority order:
      1. The Gmail thread each send created — every message in it that isn't
         ours is a reply to THAT RFQ, whatever address it came from (RFQ to
         sales@, quote from the estimator's own mailbox). Meta is known.
      2. A `from:` search for the recipient addresses — catches a supplier who
         composed a fresh email instead of replying; attributed later by
         subject (or the single-RFQ rule when no thread is on record).
    """
    pairs: List[tuple] = []
    seen_ids: set = set()
    threads_done: set = set()
    for metas in index.values():
        for meta in metas:
            thread_id = meta.get("thread_id") or ""
            if not thread_id or thread_id.startswith("mock") or thread_id in threads_done:
                continue
            threads_done.add(thread_id)
            for msg in gmail_reader.fetch_thread_replies(thread_id, skip_ids=skip_ids):
                if msg.message_id in seen_ids or (msg.from_email or "").lower() in our_addrs:
                    continue
                seen_ids.add(msg.message_id)
                pairs.append((msg, meta))
    for msg in gmail_reader.fetch_replies(
        list(index.keys()), lookback_days=settings.quote_ingest_lookback_days, skip_ids=skip_ids
    ):
        if msg.message_id in seen_ids:
            continue
        seen_ids.add(msg.message_id)
        pairs.append((msg, None))
    return pairs


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
    # ({name, qty, unitPrice, extended, leadDays} — see line_comparison.py).
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
    We derive those deterministically here — never in the LLM prompt, whose
    arithmetic was observed to drift by ~$1 — so a unit-priced reply is comparable:

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
        notes="Simulated quote (set Gmail + OpenAI keys for live ingest).",
    )
