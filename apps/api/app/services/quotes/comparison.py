"""Build a quote-comparison matrix + recommendation from ingested quotes.

Replaces the static seed COMPARISONS: pulls the project's quotes for a package,
computes the best supplier per metric, scores them on a cost/lead/risk blend, and
returns the shape the frontend comparison view already renders. Returns None when
there are no quotes yet, so the route can fall back to seed for the prototype.
"""
from typing import List, Optional

from app.models.quote import _initials
from app.repositories import quotes as quotes_repo

_LOGO_COLORS = ["#0a4d8c", "#16a34a", "#0f766e", "#b45309", "#7c3aed", "#334155"]

# Recommendation weighting: cost dominates, lead time matters, risk is a tiebreak.
_W_COST = 0.6
_W_LEAD = 0.3
_W_RISK = 0.1

# Cost and lead deltas are measured against the best quote in units a buyer
# would recognise, NOT min-max normalised: min-max makes the dearest quote
# score 1.0 whatever the gap, so with two quotes cost's 0.6 weight always beat
# lead's 0.3 — a $1 saving outranked a month of lead time. Now a price premium
# is a fraction of the cheapest total and a lead delta is days behind the
# fastest, each scaled so that PRICE_SCALE (10% dearer) and LEAD_SCALE (30
# days slower) are "one unit" of penalty. Deltas under the floors are treated
# as zero so a trivial difference can never decide an award.
_PRICE_SCALE = 0.10  # +10% over the cheapest total = 1.0 penalty unit
_PRICE_FLOOR = 0.005  # ≤0.5% dearer counts as "same price"
_LEAD_SCALE = 30.0  # 30 days behind the fastest = 1.0 penalty unit
_LEAD_FLOOR = 2.0  # ≤2 days slower counts as "same lead time"


def _money(v: Optional[float]) -> str:
    return f"${v:,.0f}" if v is not None else "—"


def _logo_bg(name: str) -> str:
    return _LOGO_COLORS[sum(ord(c) for c in (name or "x")) % len(_LOGO_COLORS)]


def _risk_score(q: dict) -> int:
    """0–100; higher is safer. Driven by lead time + quote completeness."""
    score = 100
    lead = q.get("leadDays")
    if lead is not None:
        score -= min(40, lead)
    else:
        score -= 25
    if q.get("total") is None:
        score -= 20
    if not q.get("supplierEmail"):
        score -= 5
    return max(40, min(100, score))


def _risk_label(score: int) -> str:
    band = "Low" if score >= 85 else "Med" if score >= 70 else "High"
    return f"{score} · {band}"


def _best_min(vals: List[Optional[float]]) -> int:
    """Index of the smallest non-null value, or -1 if all null."""
    best_i, best_v = -1, None
    for i, v in enumerate(vals):
        if v is None:
            continue
        if best_v is None or v < best_v:
            best_i, best_v = i, v
    return best_i


def _relative_penalties(
    vals: List[Optional[float]], scale: float, floor: float, relative: bool
) -> List[float]:
    """Penalty per value: how far it sits behind the best, in `scale` units.

    `relative=True` measures the delta as a fraction of the best (prices);
    `relative=False` measures it in absolute units (days). Deltas within
    `floor` count as zero. A missing value is always worse than every present
    one (one full unit beyond the worst), so an incomplete quote can never be
    recommended over a complete one on that axis.
    """
    present = [v for v in vals if v is not None]
    if not present:
        return [0.0 for _ in vals]
    best = min(present)
    out: List[Optional[float]] = []
    for v in vals:
        if v is None:
            out.append(None)
            continue
        delta = v - best
        if relative:
            delta = delta / best if best > 0 else 0.0
        out.append(max(0.0, delta - floor) / scale)
    worst = max(x for x in out if x is not None)
    return [x if x is not None else worst + 1.0 for x in out]


def build_comparison(
    db, org_id: str, project_id: str, package: str, package_label: str
) -> Optional[dict]:
    quotes = quotes_repo.list_quotes(db, org_id, project_id, package)
    if not quotes:
        return None

    names = [q["supplierName"] or "Supplier" for q in quotes]
    totals = [q.get("total") for q in quotes]
    materials = [q.get("materialCost") for q in quotes]
    freights = [q.get("freight") for q in quotes]
    leads = [float(q["leadDays"]) if q.get("leadDays") is not None else None for q in quotes]
    risks = [_risk_score(q) for q in quotes]

    # --- recommendation: weighted blend (lower total/lead better, higher risk better)
    cost_pen = _relative_penalties(totals, _PRICE_SCALE, _PRICE_FLOOR, relative=True)
    lead_pen = _relative_penalties(leads, _LEAD_SCALE, _LEAD_FLOOR, relative=False)
    scores = []
    for i in range(len(quotes)):
        risk = 1.0 - (risks[i] / 100.0)
        scores.append(_W_COST * cost_pen[i] + _W_LEAD * lead_pen[i] + _W_RISK * risk)
    rec_idx = scores.index(min(scores)) if scores else 0

    suppliers = [
        {"name": names[i], "logo": _initials(names[i]), "logoBg": _logo_bg(names[i]), "rec": i == rec_idx}
        for i in range(len(quotes))
    ]

    rows = [
        {"label": "Material Cost", "vals": [_money(v) for v in materials], "best": _best_min(materials)},
        {"label": "Freight", "vals": [_money(v) for v in freights], "best": _best_min(freights)},
        {"label": "Total Cost", "vals": [_money(v) for v in totals], "best": _best_min(totals), "emph": True},
        {
            "label": "Lead Time",
            "vals": [f"{int(l)} days" if l is not None else "—" for l in leads],
            "best": _best_min(leads),
        },
        {
            "label": "Risk Score",
            "vals": [_risk_label(r) for r in risks],
            "best": risks.index(max(risks)) if risks else -1,
        },
    ]

    reasons = _reasons(rec_idx, totals, leads, risks)
    savings, savings_note = _savings(rec_idx, totals)

    return {
        "pkg": package_label or package,
        "suppliers": suppliers,
        "rows": rows,
        "recommendation": names[rec_idx],
        "reasons": reasons,
        "savings": savings,
        "savingsNote": savings_note,
    }


def _reasons(rec_idx, totals, leads, risks) -> List[str]:
    out: List[str] = []
    if totals[rec_idx] is not None and totals[rec_idx] == _safe_min(totals):
        out.append("Lowest total bid")
    if leads[rec_idx] is not None and leads[rec_idx] == _safe_min(leads):
        out.append(f"Fastest lead time at {int(leads[rec_idx])} days")
    if risks[rec_idx] == max(risks):
        out.append(f"Lowest delivery risk (score {risks[rec_idx]})")
    if not out:  # recommended on blended value rather than winning any single metric
        out.append("Best overall balance of cost, lead time, and risk")
    return out


def _savings(rec_idx, totals) -> tuple:
    valid = [t for t in totals if t is not None]
    rec_total = totals[rec_idx]
    if rec_total is None or len(valid) < 2:
        return "—", "Awaiting more quotes to compute savings"
    highest = max(valid)
    saved = highest - rec_total
    pct = (saved / highest * 100) if highest else 0
    return f"${saved:,.0f}", f"{pct:.0f}% below the highest competing bid"


def _safe_min(vals):
    valid = [v for v in vals if v is not None]
    return min(valid) if valid else None
