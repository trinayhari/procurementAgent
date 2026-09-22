"""Award a package: the one code path behind the dashboard's award button and
the approval link (POST /api/approvals/{token}).

Exactly-once: the whole award (the already-awarded check, the decision row,
the PO numbers, the quote flips and the supplier notifications) runs under a
lock keyed by (org, project, package). Overlapping requests (a triple-clicked
confirm, an email click racing the dashboard) lose with a 409 immediately.

Errors are raised as HTTPException so both callers (routes) can return them
as-is; an in-process caller (the Slack button) catches HTTPException and reads
`.status_code` / `.detail`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import locks
from app.repositories import audit as audit_repo
from app.repositories import documents as documents_repo
from app.repositories import organizations as organizations_repo
from app.repositories import package_recommendations as recommendations_repo
from app.repositories import projects as projects_repo
from app.repositories import purchase_decisions as purchase_decisions_repo
from app.repositories import quotes as quotes_repo
from app.schemas.quote import AwardRequest
from app.services import notify
from app.services.notify import kinds, links
from app.services.quotes import line_comparison as line_comparison_service
from app.services.rfq import award_notify
from app.services.rfq import sender as rfq_sender
from app.services.sourcing import packages


@dataclass(frozen=True)
class Actor:
    """Who made the award. A signed-in User, or the person behind an
    approval-link click (who may have no account). Carries just what the
    audit trail, the decision row and the supplier emails need."""

    id: str
    email: str
    name: str = ""
    company: str = ""
    cc_email: Optional[str] = None

    @classmethod
    def from_user(cls, user) -> "Actor":
        return cls(
            id=user.id,
            email=user.email,
            name=getattr(user, "name", "") or "",
            company=getattr(user, "company", "") or "",
            cc_email=getattr(user, "cc_email", None),
        )


def resolve_package(db: Session, org_id: str, project_id: str, pkg: str) -> Tuple[Optional[str], str]:
    """(key, label) for a package reference from a URL or a token.

    `pkg` may be a preset key ("water"), a preset label ("Water Utilities"),
    or, for a custom BOM / subcontractor trade, the document id or its name.
    Returns (None, pkg) when nothing matches.
    """
    key = pkg if packages.is_valid(pkg) else packages.category_for_label(pkg)
    if key:
        return key, packages.label_for(key)
    doc = documents_repo.find_package_doc(db, org_id, project_id, pkg)
    if doc is not None:
        return doc.id, doc.name
    return None, pkg


def award_package(
    db: Session, org_id: str, project_id: str, pkg: str, payload: AwardRequest, actor: Actor
) -> dict:
    """Submit a (possibly split) award for a package and issue the purchase orders.

    Returns the AwardResult payload (see schemas/quote.py) including
    `poNumbers`. Raises HTTPException: 404 no quotes, 409 already awarded (and
    not `payload.supersede`), 409 nothing priced, 409 award in progress.
    """
    key, label = resolve_package(db, org_id, project_id, pkg)
    with locks.exclusive(
        f"award:{org_id}:{project_id}:{key or pkg}",
        f"{label} is being awarded right now: wait for it to finish",
    ):
        return _award_locked(db, org_id, project_id, key or pkg, label, payload, actor)


def _award_locked(db, org_id, project_id, package, pkg_label, payload, actor: Actor) -> dict:
    previous = purchase_decisions_repo.latest_for_package(db, org_id, project_id, package)
    if previous is not None and not payload.supersede:
        who = ", ".join(previous.get("suppliers") or []) or "a supplier"
        raise HTTPException(
            status_code=409,
            detail=(
                f"{pkg_label} was already awarded to {who}. "
                "Re-awarding issues new purchase orders and emails every supplier "
                "again. Confirm the re-award to proceed."
            ),
        )
    summary = line_comparison_service.compute_award(
        db, org_id, project_id, package, payload.selections
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="No quotes to award for package")
    if not summary.get("poCount"):
        raise HTTPException(
            status_code=409,
            detail="Nothing to award: the quotes for this package have no priced line items",
        )
    # One PO number per winning supplier, from the org counter. Staged with
    # the decision so the counter bump and the numbers commit together.
    po_numbers = _assign_po_numbers(db, org_id, project_id, package, summary)
    # Stage the decision + audit record on the session, then let award_package's
    # commit persist everything atomically with the quote status flips.
    decision = purchase_decisions_repo.add_decision(
        db,
        org_id,
        project_id=project_id,
        package=package,
        package_label=pkg_label,
        summary=summary,
        selections=payload.selections,
        strategy=payload.strategy,
        decided_by=actor,
        po_numbers=po_numbers,
    )
    audit_repo.log(
        db, org_id, actor, "package.awarded", "purchase_decision", decision.id,
        project_id=project_id,
        detail={
            "package": package,
            "suppliers": summary["suppliers"],
            "total": summary["total"],
            "strategy": payload.strategy,
            "supersedes": previous["id"] if previous is not None else None,
            "poNumbers": [p["po"] for p in po_numbers],
        },
        commit=False,
    )
    if previous is not None:
        # Only one live PO set per package: the earlier decision is superseded.
        purchase_decisions_repo.mark_superseded(db, org_id, previous["id"], decision.id)
    quotes_repo.award_package(db, org_id, project_id, package, summary["supplierIds"])
    # The standing recommendation (if the agent announced one) is settled.
    recommendations_repo.supersede(db, org_id, project_id, package)

    # Notify suppliers of the outcome, threaded into each RFQ conversation. Runs
    # after the award is committed so a flaky email never rolls back the award.
    notify_result = award_notify.notify_award(
        db,
        org_id=org_id,
        project_id=project_id,
        package=package,
        package_label=pkg_label,
        summary=summary,
        buyer=actor,
        sender=rfq_sender.get_sender(),
        superseded=previous,
        po_numbers=po_numbers,
    )
    n_awarded, n_declined = len(notify_result["notified"]), len(notify_result["declined"])
    n_withdrawn = len(notify_result.get("withdrawn") or [])
    purchase_decisions_repo.set_notifications(
        db, org_id, decision.id, notification_record(notify_result)
    )
    if n_awarded or n_declined or notify_result["failed"]:
        audit_repo.log(
            db, org_id, actor, "package.award_notified", "purchase_decision",
            decision.id,
            project_id=project_id,
            detail={
                "awarded": [w["email"] for w in notify_result["notified"]],
                "declined": [d["email"] for d in notify_result["declined"]],
                "withdrawn": [d["email"] for d in notify_result.get("withdrawn") or []],
                "failed": notify_result["failed"],
                "mock": notify_result["mock"],
            },
        )

    n = summary["poCount"]
    sup_list = ", ".join(summary["suppliers"])
    po_word = "PO" if n == 1 else "POs"
    notice = ""
    if n_awarded:
        notice = f" {n_awarded} supplier{'s' if n_awarded != 1 else ''} notified"
        notice += f", {n_declined} not selected." if n_declined else "."
    if n_withdrawn:
        notice += f" {n_withdrawn} previous winner{'s' if n_withdrawn != 1 else ''} told their PO is withdrawn."
    if notify_result["failed"]:
        who = "; ".join(
            f"{f.get('supplier') or f.get('email') or 'supplier'} ({f.get('error')})"
            for f in notify_result["failed"]
        )
        n_failed = len(notify_result["failed"])
        notice += (
            f" {n_failed} notification{'s' if n_failed != 1 else ''} could not be sent: {who}."
        )
    message = (
        f"Awarded {pkg_label} for "
        f"${summary['total']:,.0f}: {n} {po_word} to {sup_list}." + notice
    )
    # award.approved + po.issued notices (they also write the activity feed).
    _emit_award_notices(db, org_id, project_id, package, pkg_label, summary, po_numbers, actor)
    return {
        "status": "awarded",
        "message": message,
        "total": summary["total"],
        "material": summary["material"],
        "freight": summary["freight"],
        "leadDays": summary["leadDays"],
        "suppliers": summary["suppliers"],
        "poCount": n,
        "poNumbers": po_numbers,
        "notified": n_awarded,
        "declined": n_declined,
        "withdrawn": n_withdrawn,
        "notifyFailed": notify_result["failed"],
        "notifyMocked": notify_result["mock"],
    }


def _assign_po_numbers(db, org_id, project_id, package, summary) -> list:
    """[{supplierId, supplierName, po}] for the winners, in supplier-name order."""
    quotes = quotes_repo.list_quotes(db, org_id, project_id, package)
    names = {}
    for q in quotes:
        sid = q.get("supplierId") or q.get("supplierName") or ""
        names.setdefault(sid, q.get("supplierName") or sid)
    winners = sorted(summary.get("supplierIds") or [], key=lambda s: (names.get(s, s), s))
    numbers = organizations_repo.issue_po_numbers(db, org_id, len(winners))
    return [
        {"supplierId": sid, "supplierName": names.get(sid, sid), "po": po}
        for sid, po in zip(winners, numbers)
    ]


def _emit_award_notices(db, org_id, project_id, package, pkg_label, summary, po_numbers, actor):
    project = projects_repo.get_project(db, org_id, project_id) or {}
    project_name = project.get("name") or "Project"
    sup_list = ", ".join(summary["suppliers"])
    n = summary["poCount"]
    lines = [f"Total ${summary['total']:,.0f}: ${summary['material']:,.0f} material, "
             f"${summary['freight']:,.0f} freight"]
    if summary.get("leadDays") is not None:
        lines.append(f"Lead time {summary['leadDays']}d")
    lines.append(("Split award" if n > 1 else "Single supplier") + f", approved by {actor.email}")
    notify.emit(db, notify.Notice(
        org_id=org_id, project_id=project_id, kind=kinds.AWARD_APPROVED,
        title=f"{project_name}: {pkg_label} awarded to {sup_list}",
        lines=lines,
        actions=[notify.Action("See the award", url=links.comparison_url(project_id, package))],
        meta={"package": package, "total": summary["total"]},
    ))
    # Per-winner subtotal (their lines + their freight) next to each PO number.
    per_supplier = _per_supplier_totals(db, org_id, project_id, package, summary)
    po_lines = [
        f"{p['po']} issued to {p['supplierName']}, ${per_supplier.get(p['supplierId'], 0):,.0f}"
        for p in po_numbers
    ]
    notify.emit(db, notify.Notice(
        org_id=org_id, project_id=project_id, kind=kinds.PO_ISSUED,
        title=f"{project_name}: {n} {'PO' if n == 1 else 'POs'} issued for {pkg_label}",
        lines=po_lines or [f"${summary['total']:,.0f} to {sup_list}"],
        meta={"package": package, "poNumbers": [p["po"] for p in po_numbers]},
    ))


def _per_supplier_totals(db, org_id, project_id, package, summary) -> dict:
    """supplierId -> lines awarded to them + their freight."""
    quotes = quotes_repo.list_quotes(db, org_id, project_id, package)
    selections = summary.get("selections") or {}
    out = {}
    for q in quotes:
        sid = q.get("supplierId") or q.get("supplierName") or ""
        if sid not in (summary.get("supplierIds") or set()) or sid in out:
            continue
        won = {name for name, s in selections.items() if s == sid}
        subtotal = sum(
            li.get("extended") or 0.0 for li in q.get("lineItems", []) if li.get("name") in won
        )
        out[sid] = round(subtotal + (q.get("freight") or 0.0), 2)
    return out


def notification_record(notify_result: dict) -> dict:
    return {
        "notified": notify_result["notified"],
        "declined": notify_result["declined"],
        "withdrawn": notify_result.get("withdrawn") or [],
        "failed": notify_result["failed"],
        "mock": notify_result["mock"],
        "at": datetime.now(timezone.utc).isoformat(),
    }
