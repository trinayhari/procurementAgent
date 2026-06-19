"""Line-by-line quote comparison + freight-aware mix-and-match award optimizer.

Where comparison.py builds the supplier-vs-metric *summary* matrix, this builds the
line-vs-supplier grid the buyer uses to award a package line by line. It also
computes award *strategies*:

- mix      — lowest delivered cost. Solved exactly over supplier subsets so a line
             is only split to another supplier when its material saving beats that
             supplier's freight (i.e. freight/distance are respected, not ignored).
- fastest  — each line from its quickest supplier; minimizes package completion.
- single   — the cheapest single supplier that can cover the whole package.

All three return a {lineName: supplierId} selection the UI can preview and the
award endpoint can submit; the buyer can also hand-tune any line.
"""
from itertools import combinations
from typing import Dict, List, Optional

from app.models.quote import _initials
from app.repositories import quotes as quotes_repo
from app.services.quotes.sample_data import budget_for

_LOGO_COLORS = ["#0a4d8c", "#16a34a", "#0f766e", "#b45309", "#7c3aed", "#334155"]


def _logo_bg(name: str) -> str:
    return _LOGO_COLORS[sum(ord(c) for c in (name or "x")) % len(_LOGO_COLORS)]


def _line_map(quote: dict) -> Dict[str, dict]:
    """name -> line dict for one supplier's quote."""
    return {li["name"]: li for li in quote.get("lineItems", []) if li.get("name")}


def _cost_of(selection: Dict[str, str], lines: List[str], by_sup: Dict[str, dict],
             freight: Dict[str, float]) -> Optional[dict]:
    """Cost/lead/logistics for a {line: supplierId} selection. None if incomplete."""
    material = 0.0
    lead = 0
    used: set = set()
    for name in lines:
        sup_id = selection.get(name)
        if sup_id is None:
            return None
        li = by_sup[sup_id].get(name)
        if li is None or li.get("extended") is None:
            return None
        material += li["extended"]
        if li.get("leadDays") is not None:
            lead = max(lead, int(li["leadDays"]))
        used.add(sup_id)
    freight_total = sum(freight.get(s, 0.0) for s in used)
    return {
        "material": round(material, 2),
        "freight": round(freight_total, 2),
        "total": round(material + freight_total, 2),
        "leadDays": lead or None,
        "suppliersUsed": len(used),
        "used": used,
    }


def build_line_comparison(
    db, project_id: str, package: str, package_label: str
) -> Optional[dict]:
    quotes = quotes_repo.list_quotes(db, project_id, package)
    if not quotes:
        return None

    suppliers = [
        {
            "id": q.get("supplierId") or q.get("supplierName") or f"sup{i}",
            "name": q.get("supplierName") or "Supplier",
            "logo": _initials(q.get("supplierName") or "Supplier"),
            "logoBg": _logo_bg(q.get("supplierName") or "Supplier"),
            "leadDays": q.get("leadDays"),
            "distanceMiles": q.get("distanceMiles"),
            "freight": q.get("freight"),
            "total": q.get("total"),
        }
        for i, q in enumerate(quotes)
    ]
    sup_ids = [s["id"] for s in suppliers]
    freight = {s["id"]: (s["freight"] or 0.0) for s in suppliers}
    by_sup: Dict[str, dict] = {
        s["id"]: _line_map(q) for s, q in zip(suppliers, quotes)
    }

    # Canonical line order: first appearance across suppliers.
    line_names: List[str] = []
    line_meta: Dict[str, dict] = {}
    for q in quotes:
        for li in q.get("lineItems", []):
            name = li.get("name")
            if name and name not in line_meta:
                line_names.append(name)
                line_meta[name] = {"name": name, "qty": li.get("qty", "")}

    lines = []
    for name in line_names:
        cells = []
        best_id, best_ext = None, None
        for sid in sup_ids:
            li = by_sup[sid].get(name)
            ext = li.get("extended") if li else None
            cells.append(
                {
                    "supplierId": sid,
                    "unitPrice": li.get("unitPrice") if li else None,
                    "extended": ext,
                    "leadDays": li.get("leadDays") if li else None,
                    "available": li is not None,
                    "best": False,
                }
            )
            if ext is not None and (best_ext is None or ext < best_ext):
                best_id, best_ext = sid, ext
        for c in cells:
            c["best"] = c["supplierId"] == best_id and best_id is not None
        lines.append(
            {**line_meta[name], "cells": cells, "bestSupplierId": best_id}
        )

    # ---- strategies -------------------------------------------------------
    # single: cheapest supplier covering every line.
    single_sel, single_cost = None, None
    for sid in sup_ids:
        sel = {name: sid for name in line_names}
        cost = _cost_of(sel, line_names, by_sup, freight)
        if cost and (single_cost is None or cost["total"] < single_cost["total"]):
            single_sel, single_cost = sel, cost

    # mix: exact over supplier subsets (n is tiny) so freight is respected.
    mix_sel, mix_cost = single_sel, single_cost
    for r in range(1, len(sup_ids) + 1):
        for subset in combinations(sup_ids, r):
            sel = {}
            ok = True
            for name in line_names:
                cheapest, cheapest_ext = None, None
                for sid in subset:
                    li = by_sup[sid].get(name)
                    ext = li.get("extended") if li else None
                    if ext is not None and (cheapest_ext is None or ext < cheapest_ext):
                        cheapest, cheapest_ext = sid, ext
                if cheapest is None:
                    ok = False
                    break
                sel[name] = cheapest
            if not ok:
                continue
            cost = _cost_of(sel, line_names, by_sup, freight)
            if cost and (mix_cost is None or cost["total"] < mix_cost["total"]):
                mix_sel, mix_cost = sel, cost

    # fastest: each line from its quickest supplier (tie-break cheaper).
    fast_sel = {}
    for name in line_names:
        best_sid, best_lead, best_ext = None, None, None
        for sid in sup_ids:
            li = by_sup[sid].get(name)
            if not li or li.get("leadDays") is None:
                continue
            lead, ext = int(li["leadDays"]), li.get("extended")
            if best_lead is None or lead < best_lead or (
                lead == best_lead and ext is not None and (best_ext is None or ext < best_ext)
            ):
                best_sid, best_lead, best_ext = sid, lead, ext
        if best_sid is not None:
            fast_sel[name] = best_sid
    fast_cost = _cost_of(fast_sel, line_names, by_sup, freight) if fast_sel else None

    baseline = single_cost["total"] if single_cost else None
    dist = {s["id"]: s["distanceMiles"] for s in suppliers}

    def _option(key, label, sel, cost, note):
        if not cost:
            return None
        savings = round(baseline - cost["total"], 2) if baseline is not None else 0.0
        used = cost["used"]
        max_dist = max((dist[s] for s in used if dist.get(s) is not None), default=None)
        return {
            "key": key,
            "label": label,
            "total": cost["total"],
            "material": cost["material"],
            "freight": cost["freight"],
            "leadDays": cost["leadDays"],
            "suppliersUsed": cost["suppliersUsed"],
            "deliveries": cost["suppliersUsed"],
            "maxDistance": max_dist,
            "savings": savings,
            "note": note,
            "selections": sel,
        }

    mix_note = (
        "Split across {n} suppliers for the lowest delivered cost".format(n=mix_cost["suppliersUsed"])
        if mix_cost and mix_cost["suppliersUsed"] > 1
        else "One supplier already gives the lowest delivered cost"
    )
    options = [
        _option("mix", "Lowest cost (mix & match)", mix_sel, mix_cost, mix_note),
        _option("fastest", "Fastest delivery", fast_sel, fast_cost,
                "Each line from its quickest supplier"),
        _option("single", "Single supplier", single_sel, single_cost,
                "Award the whole package to one supplier"),
    ]
    options = [o for o in options if o is not None]

    return {
        "pkg": package_label or package,
        "package": package,
        "budget": budget_for(package) or None,
        "suppliers": suppliers,
        "lines": lines,
        "options": options,
        "recommendedOption": "mix",
    }


def compute_award(
    db, project_id: str, package: str, selections: Dict[str, str]
) -> Optional[dict]:
    """Cost/lead/supplier summary for a submitted {line: supplierId} selection.

    Returns None when there are no quotes. Unknown lines are ignored; lines left
    unassigned fall back to that package's cheapest available supplier so a partial
    submission still produces a complete, awardable basket.
    """
    quotes = quotes_repo.list_quotes(db, project_id, package)
    if not quotes:
        return None

    suppliers = {
        (q.get("supplierId") or q.get("supplierName")): q for q in quotes
    }
    freight = {sid: (q.get("freight") or 0.0) for sid, q in suppliers.items()}
    by_sup = {sid: _line_map(q) for sid, q in suppliers.items()}
    id_to_name = {sid: q.get("supplierName") or sid for sid, q in suppliers.items()}

    line_names: List[str] = []
    for q in quotes:
        for li in q.get("lineItems", []):
            if li.get("name") and li["name"] not in line_names:
                line_names.append(li["name"])

    resolved: Dict[str, str] = {}
    for name in line_names:
        sid = selections.get(name)
        if sid not in by_sup or by_sup[sid].get(name) is None:
            # fall back to cheapest available supplier for this line
            cheapest, cheapest_ext = None, None
            for s, lm in by_sup.items():
                li = lm.get(name)
                ext = li.get("extended") if li else None
                if ext is not None and (cheapest_ext is None or ext < cheapest_ext):
                    cheapest, cheapest_ext = s, ext
            sid = cheapest
        if sid is not None:
            resolved[name] = sid

    cost = _cost_of(resolved, line_names, by_sup, freight)
    if cost is None:
        return None
    used = cost["used"]
    return {
        "selections": resolved,
        "total": cost["total"],
        "material": cost["material"],
        "freight": cost["freight"],
        "leadDays": cost["leadDays"],
        "suppliers": sorted({id_to_name.get(s, s) for s in used}),
        "supplierIds": used,
        "poCount": len(used),
    }
