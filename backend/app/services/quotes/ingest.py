"""Ingest supplier quote replies for a project.

Live path: read Gmail replies from the RFQ recipients, parse each into structured
terms, and persist one quote per supplier (deduped by Gmail message id). Mock path
(no Gmail/OpenAI creds): synthesize deterministic, comparable quotes for each
recipient so the whole quote→compare flow is exercisable offline — mirroring how
sourcing/extraction fall back to mocks.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.repositories import quotes as quotes_repo
from app.repositories import rfqs as rfqs_repo
from app.services.quotes import gmail_reader, parser
from app.services.rfq.sender import is_configured as gmail_configured

logger = logging.getLogger("procureai.quotes.ingest")

# Rough per-package material baseline (USD) for the offline mock.
_PKG_BASE = {"water": 490_000, "sewer": 215_000, "storm": 260_000, "erosion": 70_000}


def _recipient_index(db: Session, project_id: str) -> Dict[str, dict]:
    """email → {rfq_id, package, package_label, supplier_id, supplier_name}."""
    index: Dict[str, dict] = {}
    for rfq in rfqs_repo.list_awaiting_rfqs(db, project_id):
        for r in rfq.get("recipients", []):
            email = (r.get("email") or "").strip().lower()
            if email and email not in index:
                index[email] = {
                    "rfq_id": rfq["id"],
                    "package": rfq["package"],
                    "package_label": rfq.get("pkg") or rfq["package"],
                    "supplier_id": r.get("supplierId"),
                    "supplier_name": r.get("name") or email,
                    "rfq_lines": rfq.get("lineItems") or [],
                }
    return index


def ingest_quotes(db: Session, project_id: str) -> Tuple[int, int, bool]:
    """Return (ingested_count, total_recipients, mocked)."""
    index = _recipient_index(db, project_id)
    total = len(index)
    if total == 0:
        return 0, 0, not (gmail_configured() and parser.is_configured())

    if gmail_configured():
        return _ingest_live(db, project_id, index)
    return _ingest_mock(db, project_id, index), total, True


def _ingest_live(db: Session, project_id: str, index: Dict[str, dict]) -> Tuple[int, int, bool]:
    seen = quotes_repo.message_ids_for_project(db, project_id)
    try:
        messages = gmail_reader.fetch_replies(
            list(index.keys()), lookback_days=settings.quote_ingest_lookback_days
        )
    except gmail_reader.GmailReadUnavailable as exc:
        logger.warning("Gmail read unavailable: %s", exc)
        raise

    ingested = 0
    quoted_rfqs: set = set()
    for msg in messages:
        if msg.message_id in seen:
            continue
        meta = index.get(msg.from_email)
        if meta is None:
            continue
        parsed = parser.parse_quote(msg.combined_text)
        if not parsed.is_quote:
            continue
        _persist(db, project_id, meta, parsed, source="gmail", message_id=msg.message_id, email=msg.from_email)
        seen.add(msg.message_id)
        ingested += 1
        if meta["rfq_id"]:
            quoted_rfqs.add(meta["rfq_id"])

    for rfq_id in quoted_rfqs:
        rfqs_repo.mark_rfq_quoted(db, rfq_id)
    return ingested, len(index), False


def _ingest_mock(db: Session, project_id: str, index: Dict[str, dict]) -> int:
    ingested = 0
    quoted_rfqs: set = set()
    for email, meta in index.items():
        if quotes_repo.has_quote_for_recipient(db, project_id, meta["package"], email):
            continue
        parsed = _mock_quote(meta["supplier_name"], meta["package"], meta.get("rfq_lines"))
        _persist(db, project_id, meta, parsed, source="mock", message_id=None, email=email)
        ingested += 1
        if meta["rfq_id"]:
            quoted_rfqs.add(meta["rfq_id"])
    for rfq_id in quoted_rfqs:
        rfqs_repo.mark_rfq_quoted(db, rfq_id)
    return ingested


def _persist(db, project_id, meta, parsed, *, source, message_id, email=None) -> None:
    # Normalize parsed lines into the shape the comparison engine reads
    # ({name, qty, unitPrice, extended, leadDays} — see line_comparison.py).
    line_items = [
        {
            "name": li.name,
            "qty": li.quantity or "",
            "unitPrice": li.unit_price,
            "extended": li.extended,
            "leadDays": parsed.lead_days,
        }
        for li in parsed.line_items
        if li.name
    ]
    quotes_repo.create_quote(
        db,
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
        status="received",
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
