"""Is a package ready to award, and what would the agent recommend?

Ready when at least one quote exists for the package and either every
supplier the RFQ went to has quoted, or the oldest send is older than the
second follow-up window (`settings.followup_second_delay_hours`): by then the
silent suppliers have been chased twice and the buyer should not wait on them.

The recommendation is the line-comparison service's "mix" strategy (lowest
delivered cost, freight respected), shaped as the AwardRequest the approval
link will submit plus the display figures the award card shows.

`announce()` is the idempotent entry point the ingest job calls: it evaluates,
skips when the same quote set was already announced (a second ingest pass over
the same replies must not re-send the card), mints the approval token, records
the recommendation and emits award.ready.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.config import settings
from app.repositories import approval_tokens as tokens_repo
from app.repositories import package_recommendations as recommendations_repo
from app.repositories import projects as projects_repo
from app.repositories import purchase_decisions as purchase_decisions_repo
from app.repositories import quotes as quotes_repo
from app.repositories import rfqs as rfqs_repo
from app.services import notify
from app.services.notify import kinds, links
from app.services.quotes import line_comparison as line_comparison_service
from app.services.rfq import state as rfq_state

logger = logging.getLogger("procureai.rfq.readiness")


@dataclass
class Recommendation:
    package: str
    package_label: str
    # The AwardRequest the approval link submits (see schemas/quote.py).
    award: dict
    suppliers: List[dict] = field(default_factory=list)  # per-supplier breakdown
    supplier_names: List[str] = field(default_factory=list)
    total: float = 0.0
    material: float = 0.0
    freight: float = 0.0
    lead_days: Optional[int] = None
    # Delivered-cost saving against the cheapest single supplier (0 when the
    # recommendation IS a single supplier).
    savings: float = 0.0
    single_total: Optional[float] = None
    quotes_received: int = 0
    recipients_total: int = 0
    quote_ids: List[str] = field(default_factory=list)

    @property
    def split(self) -> bool:
        return len(self.suppliers) > 1

    def to_payload(self) -> dict:
        d = asdict(self)
        d["quoteIds"] = sorted(self.quote_ids)
        return d


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _sent_recipients(db: Session, org_id: str, project_id: str, package: str):
    """(emails, supplier ids, oldest send) across the package's sent RFQs."""
    emails: Set[str] = set()
    sids: Set[str] = set()
    oldest: Optional[datetime] = None
    for rfq in rfqs_repo.list_rfqs(db, org_id, project_id):
        if rfq.get("package") != package:
            continue
        sent_at = rfq.get("sentAt")
        for r in rfq.get("recipients", []):
            if not rfq_state.recipient_sent(r):
                continue
            email = (r.get("email") or "").strip().lower()
            if email:
                emails.add(email)
            if r.get("supplierId"):
                sids.add(r["supplierId"])
            if sent_at:
                try:
                    when = _as_utc(datetime.fromisoformat(sent_at))
                except ValueError:
                    continue
                if oldest is None or when < oldest:
                    oldest = when
    return emails, sids, oldest


def evaluate(db: Session, org_id: str, project_id: str, package: str) -> Optional[Recommendation]:
    """The recommendation when the package is ready to award, else None."""
    quotes = quotes_repo.list_quotes(db, org_id, project_id, package)
    if not quotes:
        return None
    emails, sids, oldest = _sent_recipients(db, org_id, project_id, package)
    quoted_emails = {(q.get("supplierEmail") or "").strip().lower() for q in quotes}
    quoted_sids = {q.get("supplierId") for q in quotes if q.get("supplierId")}
    everyone_replied = bool(emails or sids) and all(
        e in quoted_emails for e in emails
    ) and all(s in quoted_sids for s in sids)
    window_lapsed = oldest is not None and (
        datetime.now(timezone.utc) - oldest
        >= timedelta(hours=settings.followup_second_delay_hours)
    )
    if not (everyone_replied or window_lapsed):
        return None
    return describe(db, org_id, project_id, package, quotes=quotes,
                    recipients_total=len(emails or sids))


def describe(
    db: Session, org_id: str, project_id: str, package: str, *,
    selections: Optional[Dict[str, str]] = None,
    quotes: Optional[List[dict]] = None,
    recipients_total: int = 0,
) -> Optional[Recommendation]:
    """Shape the recommended (or the given) selection for display.

    With `selections` (an already-minted token's AwardRequest) the figures are
    computed for exactly that basket; otherwise the "mix" strategy is used.
    """
    quotes = quotes if quotes is not None else quotes_repo.list_quotes(db, org_id, project_id, package)
    if not quotes:
        return None
    grid = line_comparison_service.build_line_comparison(
        db, org_id, project_id, package, quotes[0].get("packageLabel") or package
    )
    if grid is None or not grid.get("options"):
        return None
    options = {o["key"]: o for o in grid["options"]}
    single = options.get("single")
    if selections is None:
        chosen = options.get(grid.get("recommendedOption") or "mix") or grid["options"][0]
        selections = chosen["selections"]
    summary = line_comparison_service.compute_award(db, org_id, project_id, package, selections)
    if summary is None or not summary.get("poCount"):
        return None
    single_total = single["total"] if single else None
    savings = round(single_total - summary["total"], 2) if single_total is not None else 0.0
    return Recommendation(
        package=package,
        package_label=grid.get("pkg") or package,
        award={"selections": summary["selections"], "strategy": "mix", "supersede": False},
        suppliers=_per_supplier(quotes, summary),
        supplier_names=list(summary["suppliers"]),
        total=summary["total"],
        material=summary["material"],
        freight=summary["freight"],
        lead_days=summary.get("leadDays"),
        savings=max(savings, 0.0),
        single_total=single_total,
        quotes_received=len(quotes),
        recipients_total=max(recipients_total, len(quotes)),
        quote_ids=sorted(q["id"] for q in quotes if q.get("id")),
    )


def _per_supplier(quotes: List[dict], summary: dict) -> List[dict]:
    selections = summary.get("selections") or {}
    winners = summary.get("supplierIds") or set()
    out: List[dict] = []
    seen: Set[str] = set()
    for q in quotes:
        sid = q.get("supplierId") or q.get("supplierName") or ""
        if sid not in winners or sid in seen:
            continue
        seen.add(sid)
        won = {name for name, s in selections.items() if s == sid}
        lines = [li for li in q.get("lineItems", []) if li.get("name") in won]
        subtotal = round(sum(li.get("extended") or 0.0 for li in lines), 2)
        freight = round(q.get("freight") or 0.0, 2)
        leads = [li["leadDays"] for li in lines if li.get("leadDays") is not None]
        out.append({
            "supplierId": sid,
            "supplierName": q.get("supplierName") or sid,
            "subtotal": subtotal,
            "freight": freight,
            "total": round(subtotal + freight, 2),
            "leadDays": max(leads) if leads else q.get("leadDays"),
        })
    out.sort(key=lambda s: s["supplierName"])
    return out


def card_lines(rec: Recommendation) -> List[str]:
    """The award card's status lines (same voice as the landing page)."""
    lines = [
        f"Quotes leveled to the line: {rec.quotes_received} of {rec.recipients_total} suppliers",
    ]
    if rec.split:
        saving = f"${rec.savings:,.0f} under best single bid, " if rec.savings > 0 else ""
        lines.append(f"Split award recommended: {saving}freight priced in")
    else:
        lines.append(f"Single supplier recommended: {rec.supplier_names[0] if rec.supplier_names else 'best bid'}, "
                     f"${rec.total:,.0f} delivered")
    leads = [s["leadDays"] for s in rec.suppliers if s.get("leadDays") is not None]
    if leads:
        lines.append("Lead time " + " / ".join(f"{int(d)}d" for d in leads))
    return lines


def announce(db: Session, org_id: str, project_id: str, package: str) -> Optional[dict]:
    """Evaluate the package and, when ready and not yet announced for this
    quote set, mint the approval token and emit award.ready. Returns the
    token row's public fields ({"token", "id"}) when a notice went out."""
    if purchase_decisions_repo.latest_for_package(db, org_id, project_id, package) is not None:
        return None  # already awarded; nothing to recommend
    rec = evaluate(db, org_id, project_id, package)
    if rec is None:
        return None
    live = recommendations_repo.live_for_package(db, org_id, project_id, package)
    if live is not None and live.quote_ids() == sorted(rec.quote_ids):
        return None  # same quotes as last time: the card already went out
    token = tokens_repo.create(
        db, org_id, project_id=project_id, package=package,
        package_label=rec.package_label, payload=rec.award,
    )
    recommendations_repo.record(
        db, org_id, project_id=project_id, package=package,
        payload=rec.to_payload(), token_id=token.id,
    )
    project = projects_repo.get_project(db, org_id, project_id) or {}
    project_name = project.get("name") or "Project"
    notify.emit(db, notify.Notice(
        org_id=org_id, project_id=project_id, kind=kinds.AWARD_READY,
        title=f"{project_name}: {rec.package_label} award ready",
        lines=card_lines(rec),
        actions=[
            notify.Action("Approve award", url=links.approve_url(token.token), style="primary"),
            notify.Action("See the comparison", url=links.comparison_url(project_id, package)),
        ],
        meta={"package": package, "total": rec.total, "tokenId": token.id,
              "suppliers": rec.supplier_names},
    ))
    logger.info("award.ready announced for %s/%s (token %s)", project_id, package, token.id)
    return {"token": token.token, "id": token.id}
