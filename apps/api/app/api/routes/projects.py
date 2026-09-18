from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import locks
from app.core.security import get_current_user
from app.db import DEMO_ORG_ID, get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import documents as documents_repo
from app.repositories import events as events_repo
from app.repositories import lenders as lenders_repo
from app.repositories import projects as projects_repo
from app.repositories import purchase_decisions as purchase_decisions_repo
from app.repositories import quotes as quotes_repo
from app.repositories import reference as reference_repo
from app.repositories import suppliers as suppliers_repo
from app.repositories import timeline as timeline_repo
from app.services import schedule as schedule_service
from app.services.quotes import comparison as comparison_service
from app.services.quotes import line_comparison as line_comparison_service
from app.services.rfq import award_notify
from app.services.rfq import sender as rfq_sender
from app.services.sourcing import packages
from app.schemas.document import Document, LineItemGroup
from app.schemas.lender import Lender, LenderCreate
from app.schemas.project import Project, ProjectCreate, ProjectDetail
from app.schemas.quote import (
    AwardNotifyRequest,
    AwardNotifyResult,
    AwardRequest,
    AwardResult,
    Comparison,
    LineComparison,
    PurchaseDecision,
    Quote,
)
from app.schemas.rfq import Rfq, RfqFolder
from app.schemas.supplier import Supplier
from app.schemas.timeline import Timeline

router = APIRouter(prefix="/api/projects", tags=["projects"])


# Projects are persisted (SQLite via SQLAlchemy) and scoped to the caller's
# organization: `_require_project` 404s for an id that exists but belongs to
# another tenant, so the response never confirms it exists. The per-project
# sub-resources below still serve prototype seed data for unextracted views.
@router.get("", response_model=List[Project])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return projects_repo.list_projects(db, current_user.organization_id)


@router.post("", response_model=Project, status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    project = projects_repo.create_project(
        db,
        org_id,
        name=payload.name,
        loc=payload.loc,
        value=payload.value,
        stage=payload.stage.value,
    )
    audit_repo.log(
        db, org_id, current_user, "project.created", "project", project["id"],
        project_id=project["id"], detail={"name": project["name"]},
    )
    events_repo.log(
        db,
        org_id,
        project["id"],
        title="Project created",
        icon="sparkles",
        tone="ai",
        meta=project["name"],
    )
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a project and all of its documents, quotes, RFQs and suppliers."""
    org_id = current_user.organization_id
    if not projects_repo.delete_project(db, org_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    audit_repo.log(
        db, org_id, current_user, "project.deleted", "project", project_id,
        project_id=project_id,
    )
    return None


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    project = _require_project(org_id, project_id, db)
    demo = _is_demo_org(org_id)
    return {
        **project,
        # Overview cards / package progress are seeded prototype literals —
        # demo org only (they were identical for every project of every tenant).
        "overviewCards": reference_repo.list_overview_cards(db) if demo else [],
        "packages": reference_repo.list_packages(db) if demo else [],
        "activity": events_repo.list_for_project(db, org_id, project_id),
    }


@router.get("/{project_id}/documents", response_model=List[Document])
def list_documents(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    docs = documents_repo.list_for_project(db, org_id, project_id)
    # Annotate each document with how many schedule events it contributed, so
    # the Documents tab can nudge the user toward the Timeline tab.
    counts = timeline_repo.counts_by_document(db, org_id, project_id)
    for d in docs:
        d["timelineEvents"] = counts.get(d["id"], 0)
    return docs


@router.get("/{project_id}/line-items", response_model=List[LineItemGroup])
def list_line_items(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    # The project-wide seed BOM is prototype material for the demo org only;
    # a real tenant's project has no "project-wide" items outside its documents.
    return reference_repo.list_line_item_groups(db) if _is_demo_org(org_id) else []


@router.get("/{project_id}/suppliers", response_model=List[Supplier])
def list_project_suppliers(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    return suppliers_repo.list_suppliers(db, org_id)


@router.get("/{project_id}/quotes", response_model=List[Quote])
def list_quotes(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    # Only this project's own (ingested or seeded) quote rows. The demo org
    # alone may fall back to the seeded Riverside quotes (keeps the demo
    # populated before any quotes are ingested); every other tenant used to see
    # the same five Riverside quotes under every project that had none of its
    # own, and "Compare" on those rows 404'd because no real quote backed them.
    rows = quotes_repo.list_quote_rows(db, org_id, project_id)
    if rows or not _is_demo_org(org_id):
        return rows
    return reference_repo.list_demo_quotes(db)


@router.get("/{project_id}/rfqs", response_model=List[Rfq])
def list_rfqs(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    return reference_repo.list_demo_rfqs(db) if _is_demo_org(org_id) else []


@router.get("/{project_id}/rfq-folders", response_model=List[RfqFolder])
def list_rfq_folders(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    return reference_repo.list_rfq_folders(db) if _is_demo_org(org_id) else []


# Lenders: the project's financing contacts. Stored per-project so timeline
# progress emails (PRO-16) know who to update.
@router.get("/{project_id}/lenders", response_model=List[Lender])
def list_lenders(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    return lenders_repo.list_for_project(db, org_id, project_id)


@router.post("/{project_id}/lenders", response_model=Lender, status_code=201)
def add_lender(
    project_id: str,
    payload: LenderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    lender = lenders_repo.create(
        db,
        org_id,
        project_id,
        name=payload.name,
        email=payload.email,
        institution=payload.institution,
        phone=payload.phone,
    )
    events_repo.log(
        db,
        org_id,
        project_id,
        title=f"Lender added: {lender['name']}",
        icon="supplier",
        tone="blue",
        meta=lender["institution"] or lender["email"],
    )
    return lender


@router.delete("/{project_id}/lenders/{lender_id}", status_code=204)
def remove_lender(
    project_id: str,
    lender_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    if lenders_repo.delete(db, org_id, project_id, lender_id) is None:
        raise HTTPException(status_code=404, detail="Lender not found")
    return None


@router.get("/{project_id}/timeline", response_model=Timeline)
def get_timeline(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The project schedule, built from timeline events extracted out of the
    project's documents. Falls back to the demo timeline (present only when
    demo seeding is enabled) while nothing has been extracted."""
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    built = schedule_service.build_schedule(
        timeline_repo.list_for_project(db, org_id, project_id)
    )
    if built is not None:
        return built
    if _is_demo_org(org_id):
        return reference_repo.get_timeline(db)
    return {"milestones": [], "gantt": [], "ganttCols": []}


@router.get("/{project_id}/packages/{pkg}/comparison", response_model=Comparison)
def get_comparison(
    project_id: str,
    pkg: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    # `pkg` may arrive as a package key ("water") or a display label
    # ("Water Utilities"); resolve to the canonical key for the quote lookup.
    key = pkg if packages.is_valid(pkg) else packages.category_for_label(pkg)
    label = packages.label_for(key) if key else pkg
    if key:
        dynamic = comparison_service.build_comparison(db, org_id, project_id, key, label)
        if dynamic is not None:
            return dynamic
    # No ingested quotes yet → prototype demo comparison (keyed by label),
    # for the demo org only.
    comparison = None
    if _is_demo_org(org_id):
        comparison = reference_repo.get_comparison(db, pkg) or (
            reference_repo.get_comparison(db, label) if key else None
        )
    if comparison is None:
        raise HTTPException(status_code=404, detail="No comparison for package")
    return comparison


@router.get(
    "/{project_id}/packages/{pkg}/line-comparison", response_model=LineComparison
)
def get_line_comparison(
    project_id: str,
    pkg: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Line-by-line quote grid + freight-aware mix-and-match award strategies."""
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    key, label = _resolve_package(db, org_id, project_id, pkg)
    result = line_comparison_service.build_line_comparison(
        db, org_id, project_id, key or pkg, label
    )
    if result is None:
        raise HTTPException(status_code=404, detail="No quotes to compare for package")
    last = purchase_decisions_repo.latest_for_package(db, org_id, project_id, key or pkg)
    if last is not None:
        result["lastAward"] = {
            "decidedAt": last.get("createdAt"),
            "decidedByEmail": last.get("decidedByEmail") or "",
            "suppliers": last.get("suppliers") or [],
            "total": last.get("total") or 0,
            "poCount": last.get("poCount") or 0,
        }
    return result


@router.post("/{project_id}/packages/{pkg}/award", response_model=AwardResult)
def award_package(
    project_id: str,
    pkg: str,
    payload: AwardRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a (possibly split) award for a package and issue the purchase orders.

    Exactly-once: the whole award — the already-awarded check, the decision
    row, the quote flips and the supplier notifications — runs under a lock
    keyed by (org, project, package). Overlapping requests (a triple-clicked
    confirm) used to all pass the check-then-insert and each issue POs and
    email every supplier; now the losers answer 409 immediately.
    """
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    key, pkg_label_for_record = _resolve_package(db, org_id, project_id, pkg)
    with locks.exclusive(
        f"award:{org_id}:{project_id}:{key or pkg}",
        f"{pkg_label_for_record} is being awarded right now — wait for it to finish",
    ):
        return _award_locked(db, org_id, project_id, pkg, key, pkg_label_for_record, payload, current_user)


def _award_locked(db, org_id, project_id, pkg, key, pkg_label_for_record, payload, current_user):
    previous = purchase_decisions_repo.latest_for_package(db, org_id, project_id, key or pkg)
    if previous is not None and not payload.supersede:
        who = ", ".join(previous.get("suppliers") or []) or "a supplier"
        raise HTTPException(
            status_code=409,
            detail=(
                f"{pkg_label_for_record} was already awarded to {who}. "
                "Re-awarding issues new purchase orders and emails every supplier "
                "again — confirm the re-award to proceed."
            ),
        )
    summary = line_comparison_service.compute_award(
        db, org_id, project_id, key or pkg, payload.selections
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="No quotes to award for package")
    if not summary.get("poCount"):
        raise HTTPException(
            status_code=409,
            detail="Nothing to award — the quotes for this package have no priced line items",
        )
    # Stage the decision + audit record on the session, then let award_package's
    # commit persist everything atomically with the quote status flips.
    decision = purchase_decisions_repo.add_decision(
        db,
        org_id,
        project_id=project_id,
        package=key or pkg,
        package_label=pkg_label_for_record,
        summary=summary,
        selections=payload.selections,
        strategy=payload.strategy,
        decided_by=current_user,
    )
    audit_repo.log(
        db, org_id, current_user, "package.awarded", "purchase_decision", decision.id,
        project_id=project_id,
        detail={
            "package": key or pkg,
            "suppliers": summary["suppliers"],
            "total": summary["total"],
            "strategy": payload.strategy,
            "supersedes": previous["id"] if previous is not None else None,
        },
        commit=False,
    )
    if previous is not None:
        # Only one live PO set per package: the earlier decision is superseded.
        purchase_decisions_repo.mark_superseded(db, org_id, previous["id"], decision.id)
    quotes_repo.award_package(db, org_id, project_id, key or pkg, summary["supplierIds"])

    # Notify suppliers of the outcome, threaded into each RFQ conversation. Runs
    # after the award is committed so a flaky email never rolls back the award.
    notify = award_notify.notify_award(
        db,
        org_id=org_id,
        project_id=project_id,
        package=key or pkg,
        package_label=pkg_label_for_record,
        summary=summary,
        buyer=current_user,
        sender=rfq_sender.get_sender(),
        superseded=previous,
    )
    n_awarded, n_declined = len(notify["notified"]), len(notify["declined"])
    n_withdrawn = len(notify.get("withdrawn") or [])
    purchase_decisions_repo.set_notifications(
        db, org_id, decision.id, _notification_record(notify)
    )
    if n_awarded or n_declined or notify["failed"]:
        audit_repo.log(
            db, org_id, current_user, "package.award_notified", "purchase_decision",
            decision.id,
            project_id=project_id,
            detail={
                "awarded": [w["email"] for w in notify["notified"]],
                "declined": [d["email"] for d in notify["declined"]],
                "withdrawn": [d["email"] for d in notify.get("withdrawn") or []],
                "failed": notify["failed"],
                "mock": notify["mock"],
            },
        )

    n = summary["poCount"]
    sup_list = ", ".join(summary["suppliers"])
    po_word = "PO" if n == 1 else "POs"
    pkg_label = pkg_label_for_record
    notice = ""
    if n_awarded:
        notice = f" {n_awarded} supplier{'s' if n_awarded != 1 else ''} notified"
        notice += f", {n_declined} not selected." if n_declined else "."
    if n_withdrawn:
        notice += f" {n_withdrawn} previous winner{'s' if n_withdrawn != 1 else ''} told their PO is withdrawn."
    if notify["failed"]:
        who = "; ".join(
            f"{f.get('supplier') or f.get('email') or 'supplier'} ({f.get('error')})"
            for f in notify["failed"]
        )
        n_failed = len(notify["failed"])
        notice += (
            f" {n_failed} notification{'s' if n_failed != 1 else ''} could not be sent: {who}."
        )
    message = (
        f"Awarded {pkg_label} for "
        f"${summary['total']:,.0f} — {n} {po_word} to {sup_list}." + notice
    )
    events_repo.log(
        db,
        org_id,
        project_id,
        title=f"{pkg_label} awarded to {sup_list}",
        icon="check",
        tone="success",
        meta=f"${summary['total']:,.0f} · {n} {po_word}"
             + (f" · {n_awarded} notified" if n_awarded else ""),
    )
    return {
        "status": "awarded",
        "message": message,
        "total": summary["total"],
        "material": summary["material"],
        "freight": summary["freight"],
        "leadDays": summary["leadDays"],
        "suppliers": summary["suppliers"],
        "poCount": n,
        "notified": n_awarded,
        "declined": n_declined,
        "withdrawn": n_withdrawn,
        "notifyFailed": notify["failed"],
        "notifyMocked": notify["mock"],
    }


def _notification_record(notify: dict) -> dict:
    return {
        "notified": notify["notified"],
        "declined": notify["declined"],
        "withdrawn": notify.get("withdrawn") or [],
        "failed": notify["failed"],
        "mock": notify["mock"],
        "at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/{project_id}/packages/{pkg}/award/notify", response_model=AwardNotifyResult)
def resend_award_notifications(
    project_id: str,
    pkg: str,
    payload: AwardNotifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-send the PO / decline emails for the package's latest award.

    By default only the suppliers whose notification failed last time are
    emailed again (the award itself is untouched); `all: true` re-notifies
    every supplier. 409 when nothing failed and `all` isn't set, 404 when the
    package has no award.
    """
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    key, pkg_label = _resolve_package(db, org_id, project_id, pkg)
    decision = purchase_decisions_repo.latest_for_package(db, org_id, project_id, key or pkg)
    if decision is None:
        raise HTTPException(status_code=404, detail="This package has not been awarded")
    previous = decision.get("notifications") or {}
    failed_emails = {f.get("email") for f in previous.get("failed", []) if f.get("email")}
    if not payload.all and not failed_emails:
        raise HTTPException(
            status_code=409,
            detail="Every supplier was already notified for this award — nothing to re-send",
        )
    summary = {
        "selections": decision.get("selections") or {},
        "supplierIds": set(decision.get("supplierIds") or []),
    }
    notify = award_notify.notify_award(
        db,
        org_id=org_id,
        project_id=project_id,
        package=key or pkg,
        package_label=decision.get("packageLabel") or pkg_label,
        summary=summary,
        buyer=current_user,
        sender=rfq_sender.get_sender(),
        only_emails=None if payload.all else failed_emails,
        superseded=purchase_decisions_repo.superseded_by_decision(db, org_id, decision["id"]),
    )
    # Merge: suppliers notified now leave the failed list; new failures replace
    # their earlier entries.
    now_ok = {e["email"] for e in notify["notified"] + notify["declined"] + (notify.get("withdrawn") or [])}
    still_failed = [f for f in previous.get("failed", []) if f.get("email") not in now_ok
                    and f.get("email") not in {x.get("email") for x in notify["failed"]}]
    merged = {
        "notified": previous.get("notified", []) + [e for e in notify["notified"]
                                                   if e["email"] not in {x["email"] for x in previous.get("notified", [])}],
        "declined": previous.get("declined", []) + [e for e in notify["declined"]
                                                   if e["email"] not in {x["email"] for x in previous.get("declined", [])}],
        "withdrawn": previous.get("withdrawn", []) + [e for e in notify.get("withdrawn") or []
                                                     if e["email"] not in {x["email"] for x in previous.get("withdrawn", [])}],
        "failed": still_failed + notify["failed"],
        "mock": notify["mock"],
        "at": datetime.now(timezone.utc).isoformat(),
    }
    purchase_decisions_repo.set_notifications(db, org_id, decision["id"], merged)
    audit_repo.log(
        db, org_id, current_user, "package.award_notified", "purchase_decision", decision["id"],
        project_id=project_id,
        detail={
            "resend": True,
            "awarded": [w["email"] for w in notify["notified"]],
            "declined": [d["email"] for d in notify["declined"]],
            "failed": notify["failed"],
            "mock": notify["mock"],
        },
    )
    n_ok = len(notify["notified"]) + len(notify["declined"]) + len(notify.get("withdrawn") or [])
    n_bad = len(notify["failed"])
    message = f"{n_ok} supplier{'s' if n_ok != 1 else ''} notified"
    if n_bad:
        message += f", {n_bad} still failing: " + "; ".join(
            f"{f.get('supplier') or f.get('email')} ({f.get('error')})" for f in notify["failed"]
        )
    return {
        "message": message + ".",
        "notified": len(notify["notified"]),
        "declined": len(notify["declined"]),
        "withdrawn": len(notify.get("withdrawn") or []),
        "notifyFailed": notify["failed"],
        "notifyMocked": notify["mock"],
    }


@router.get("/{project_id}/purchase-decisions", response_model=List[PurchaseDecision])
def list_purchase_decisions(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Award records for a project — who bought what, from whom, decided by whom."""
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    return purchase_decisions_repo.list_for_project(db, org_id, project_id)


def _is_demo_org(org_id: str) -> bool:
    """Only the seeded demo organization gets the prototype's demo data
    (quotes, RFQ inbox, comparisons, project-wide BOM) in place of empty
    per-project data. Real tenants see their own data or an empty state."""
    return org_id == DEMO_ORG_ID


def _resolve_package(db: Session, org_id: str, project_id: str, pkg: str):
    """(key, label) for a package reference from the URL.

    `pkg` may be a preset key ("water"), a preset label ("Water Utilities"),
    or — for a custom BOM / subcontractor trade — the document id or its
    name. The Quotes table groups by label, so the compare link used to 404
    for every custom package ("No quotes to compare") because only preset
    labels were mapped back to a key. Returns (None, pkg) when nothing matches.
    """
    key = pkg if packages.is_valid(pkg) else packages.category_for_label(pkg)
    if key:
        return key, packages.label_for(key)
    doc = documents_repo.find_package_doc(db, org_id, project_id, pkg)
    if doc is not None:
        return doc.id, doc.name
    return None, pkg


def _require_project(org_id: str, project_id: str, db: Session) -> dict:
    """The project, or 404.

    Deliberately 404 (not 403) when the project exists but belongs to another
    organization: a 403 would confirm the id is real.
    """
    project = projects_repo.get_project(db, org_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
