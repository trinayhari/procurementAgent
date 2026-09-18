"""Dashboard KPIs and per-project overview figures, computed from real rows.

Every number here is derived from the tenant's own projects, documents, RFQs,
quotes and purchase decisions — there are no seeded literals and no demo-only
path, so the demo organization and a brand-new tenant go through exactly the
same arithmetic. A figure that cannot be derived is not shown.

Definitions (product decisions, round 3):

- Active projects  — projects with at least one document.
- RFQs out         — RFQs in status "Awaiting" (sent, no quote back yet).
- Quotes received  — quotes ingested across the org's projects.
- Spend committed  — sum of awarded purchase-decision totals. A package that
                     was re-awarded counts its LATEST decision only: the
                     superseded award is no longer what is committed.
- Savings          — over awarded packages, Σ (highest quote total for that
                     package − awarded total). Shown only once ≥1 award exists.
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.found_supplier import FoundSupplier
from app.models.project import Project
from app.models.purchase_decision import PurchaseDecision
from app.models.quote import Quote
from app.models.rfq import Rfq
from app.services.sourcing import packages as packages_svc


def _money(v: float) -> str:
    """Compact currency for a KPI tile: $0 / $4,250 / $35.3K / $1.84M."""
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:.2f}M".replace(".00M", "M")
    if v >= 10_000:
        return f"{sign}${v / 1_000:.1f}K".replace(".0K", "K")
    return f"{sign}${v:,.0f}"


def _plural(n: int, word: str, plural: Optional[str] = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


# ------------------------------------------------------------------ awards
def _latest_decisions(
    db: Session, org_id: str, project_id: Optional[str] = None
) -> Dict[Tuple[str, str], PurchaseDecision]:
    """The most recent purchase decision per (project, package)."""
    stmt = select(PurchaseDecision).where(PurchaseDecision.organization_id == org_id)
    if project_id is not None:
        stmt = stmt.where(PurchaseDecision.project_id == project_id)
    stmt = stmt.order_by(PurchaseDecision.created_at.asc(), PurchaseDecision.id.asc())
    latest: Dict[Tuple[str, str], PurchaseDecision] = {}
    for row in db.scalars(stmt).all():
        latest[(row.project_id, row.package)] = row  # later rows overwrite earlier
    return latest


def _highest_quote_totals(
    db: Session, org_id: str, project_id: Optional[str] = None
) -> Dict[Tuple[str, str], float]:
    """Highest quoted total per (project, package), ignoring unpriced quotes."""
    stmt = (
        select(Quote.project_id, Quote.package, func.max(Quote.total))
        .where(Quote.organization_id == org_id, Quote.total.isnot(None))
        .group_by(Quote.project_id, Quote.package)
    )
    if project_id is not None:
        stmt = stmt.where(Quote.project_id == project_id)
    return {(pid, pkg): float(mx) for pid, pkg, mx in db.execute(stmt).all() if mx is not None}


def award_figures(
    db: Session, org_id: str, project_id: Optional[str] = None
) -> Tuple[int, float, float]:
    """(awarded packages, spend committed, savings) for an org or one project."""
    latest = _latest_decisions(db, org_id, project_id)
    if not latest:
        return 0, 0.0, 0.0
    highest = _highest_quote_totals(db, org_id, project_id)
    spend = sum(float(d.total or 0) for d in latest.values())
    savings = 0.0
    for key, decision in latest.items():
        top = highest.get(key)
        if top is not None:
            savings += top - float(decision.total or 0)
    return len(latest), round(spend, 2), round(savings, 2)


# --------------------------------------------------------------- dashboard
def dashboard_metrics(db: Session, org_id: str) -> List[dict]:
    """The dashboard KPI tiles for one organization (see module docstring)."""
    total_projects = db.scalar(
        select(func.count()).select_from(Project).where(Project.organization_id == org_id)
    ) or 0
    active_projects = db.scalar(
        select(func.count(func.distinct(Document.project_id)))
        .select_from(Document)
        .join(Project, Project.id == Document.project_id)
        .where(Document.organization_id == org_id, Project.organization_id == org_id)
    ) or 0
    rfqs_out = db.scalar(
        select(func.count())
        .select_from(Rfq)
        .where(Rfq.organization_id == org_id, Rfq.status == "Awaiting")
    ) or 0
    rfqs_total = db.scalar(
        select(func.count())
        .select_from(Rfq)
        .where(Rfq.organization_id == org_id, Rfq.status != "Draft")
    ) or 0
    quotes = db.scalar(
        select(func.count()).select_from(Quote).where(Quote.organization_id == org_id)
    ) or 0
    quoted_projects = db.scalar(
        select(func.count(func.distinct(Quote.project_id)))
        .select_from(Quote)
        .where(Quote.organization_id == org_id)
    ) or 0
    awarded, spend, savings = award_figures(db, org_id)

    metrics = [
        {
            "label": "Active projects",
            "value": str(active_projects),
            "delta": "",
            "sub": f"of {_plural(total_projects, 'project')} with documents",
        },
        {
            "label": "RFQs out",
            "value": str(rfqs_out),
            "delta": "",
            "sub": "awaiting quotes" + (f" · {rfqs_total} sent in total" if rfqs_total > rfqs_out else ""),
        },
        {
            "label": "Quotes received",
            "value": str(quotes),
            "delta": "",
            "sub": f"across {_plural(quoted_projects, 'project')}" if quotes else "none yet",
        },
        {
            "label": "Spend committed",
            "value": _money(spend),
            "delta": "",
            "sub": f"{_plural(awarded, 'package')} awarded" if awarded else "no awards yet",
        },
    ]
    if awarded:
        metrics.append({
            "label": "Savings",
            "value": _money(savings),
            "delta": "",
            "sub": "vs. the highest quote on each awarded package",
            "up": savings > 0,
            "ai": True,
        })
    return metrics


# ---------------------------------------------------------- project overview
_PROGRESS = [
    # (pct, tone, stage label) — reached in order; the furthest step wins.
    (100, "success", "Awarded"),
    (75, "blue", "Quotes in"),
    (50, "blue", "RFQ sent"),
    (25, "gray", "RFQ drafted"),
    (10, "gray", "Items identified"),
]


def project_overview(db: Session, org_id: str, project_id: str) -> Tuple[List[dict], List[dict]]:
    """(overview cards, package progress) for one project, from its own rows."""
    docs = db.scalars(
        select(Document).where(
            Document.organization_id == org_id, Document.project_id == project_id
        )
    ).all()
    rfqs = db.scalars(
        select(Rfq).where(Rfq.organization_id == org_id, Rfq.project_id == project_id)
    ).all()
    quotes = db.scalars(
        select(Quote).where(Quote.organization_id == org_id, Quote.project_id == project_id)
    ).all()
    found = db.scalar(
        select(func.count())
        .select_from(FoundSupplier)
        .where(FoundSupplier.organization_id == org_id, FoundSupplier.project_id == project_id)
    ) or 0
    latest = _latest_decisions(db, org_id, project_id)
    awarded, spend, savings = award_figures(db, org_id, project_id)

    analyzed = sum(1 for d in docs if d.status in ("Analyzed", "Saved"))
    confirmed = sum(1 for d in docs if d.reviewed)
    sent = [r for r in rfqs if r.status != "Draft"]
    quoted_rfqs = sum(1 for r in rfqs if r.status == "Quoted")
    drafts = len(rfqs) - len(sent)
    quoted_suppliers = len({(q.supplier_id or q.supplier_name) for q in quotes})
    quote_packages = len({q.package for q in quotes})

    cards = [
        {
            "label": "Documents",
            "value": str(len(docs)),
            "sub": (f"{analyzed} analyzed · {confirmed} confirmed" if docs else "none uploaded yet"),
            "icon": "file",
            "tone": "blue",
        },
        {
            "label": "Suppliers found",
            "value": str(found),
            "sub": (_plural(quoted_suppliers, "supplier") + " quoted") if quoted_suppliers else ("none quoted yet" if found else "run a supplier search"),
            "icon": "supplier",
            "tone": "violet",
        },
        {
            "label": "RFQs sent",
            "value": str(len(sent)),
            "sub": (f"{quoted_rfqs} quoted" + (f" · {drafts} draft{'' if drafts == 1 else 's'}" if drafts else "")) if rfqs else "none sent yet",
            "icon": "rfq",
            "tone": "blue",
        },
        {
            "label": "Quotes received",
            "value": str(len(quotes)),
            "sub": (_plural(quote_packages, "package")) if quotes else "none yet",
            "icon": "quote",
            "tone": "success",
        },
    ]
    if awarded:
        cards.append({
            "label": "Savings identified",
            "value": _money(savings),
            "sub": f"{_money(spend)} committed · {_plural(awarded, 'package')} awarded",
            "icon": "sparkles",
            "tone": "ai",
            "ai": True,
        })

    return cards, _package_progress(db, org_id, project_id, docs, rfqs, quotes, latest)


def _package_progress(db, org_id, project_id, docs, rfqs, quotes, latest) -> List[dict]:
    """One progress bar per package the project is actually working.

    A package exists once something refers to it: a custom BOM / trade scope
    document, a preset category with extracted line items, an RFQ, a quote or
    an award. Progress is the furthest step reached for that package.
    """
    labels: Dict[str, str] = {}
    order: List[str] = []

    def _add(key: str, label: str) -> None:
        if key and key not in labels:
            labels[key] = label
            order.append(key)
        elif key and label and not labels.get(key):
            labels[key] = label

    has_items: set = set()
    for d in docs:
        if d.plan_type in ("custom_bom", "trade_scope"):
            _add(d.id, d.name)
            groups = d.get_line_items() or []
            if d.plan_type == "trade_scope" or any(g.get("items") for g in groups):
                has_items.add(d.id)
            continue
        if not d.plan_type:
            continue  # seed/demo documents carry no BOM of their own
        for g in d.get_line_items() or []:
            key = packages_svc.category_for_label(g.get("group", ""))
            if key and g.get("items"):
                _add(key, packages_svc.label_for(key))
                has_items.add(key)
    for r in rfqs:
        _add(r.package, r.package_label or packages_svc.label_for(r.package))
    for q in quotes:
        _add(q.package, q.package_label or packages_svc.label_for(q.package))
    for (_pid, pkg), d in latest.items():
        _add(pkg, d.package_label or packages_svc.label_for(pkg))

    drafted = {r.package for r in rfqs}
    sent = {r.package for r in rfqs if r.status != "Draft"}
    quoted = {q.package for q in quotes}
    awarded = {pkg for (_pid, pkg) in latest}

    out = []
    for key in order:
        if key in awarded:
            pct, tone, stage = _PROGRESS[0]
        elif key in quoted:
            pct, tone, stage = _PROGRESS[1]
        elif key in sent:
            pct, tone, stage = _PROGRESS[2]
        elif key in drafted:
            pct, tone, stage = _PROGRESS[3]
        elif key in has_items:
            pct, tone, stage = _PROGRESS[4]
        else:
            pct, tone, stage = 0, "gray", "Not started"
        out.append({"name": labels[key] or key, "pct": pct, "tone": tone, "stage": stage})
    return out
