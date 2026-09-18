"""Supplier search + RFQ generation/sending for a project's buy-packages.

Search runs as a background task (geocode → Places → website email scrape is slow)
and the frontend polls GET .../suppliers/found, mirroring the document-extraction
UX. With no Google/Gmail keys the whole flow runs against mocks.
"""
import os
import re
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import SessionLocal, get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import documents as documents_repo
from app.repositories import events as events_repo
from app.repositories import jobs as jobs_repo
from app.repositories import projects as projects_repo
from app.repositories import reference as reference_repo
from app.repositories import rfqs as rfqs_repo
from app.repositories import sourcing as sourcing_repo
from app.repositories import suppliers as suppliers_repo
from app.schemas.quote import QuoteIngestResult
from app.schemas.rfq import (
    PersistedRfq,
    RfqConversation,
    RfqGenerateRequest,
    RfqUpdate,
)
from app.schemas.sourcing import (
    CustomBomSummary,
    PackageBom,
    SupplierSearchAccepted,
    SupplierSearchRequest,
    SupplierSearchResult,
    TradeScopeCreate,
    TradeScopeSummary,
    TradeScopeUpdate,
)
from app.services import storage
from app.services.quotes import ingest as quotes_ingest
from app.services.rfq import conversation as rfq_conversation
from app.services.rfq import generator as rfq_generator
from app.services.rfq import sender as rfq_sender
from app.services.rfq import state as rfq_state
from app.services.sourcing import distance, packages
from app.services.sourcing import service as sourcing_service

router = APIRouter(prefix="/api/projects", tags=["sourcing"])

# Background-task progress is persisted in the background_jobs table (see
# app.repositories.jobs) so it survives restarts and works under multiple
# workers. Job kinds used here:
SEARCH_JOB = "supplier_search"
INGEST_JOB = "quote_ingest"


def _search_ref(project_id: str, package: str) -> str:
    return f"{project_id}:{package}"


def _require_project(org_id: str, project_id: str, db: Session) -> dict:
    """The project, or 404 — including when it exists in another organization
    (a 403 there would confirm the id is real)."""
    project = projects_repo.get_project(db, org_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _require_package(org_id: str, package: str, project_id: str, db: Session) -> None:
    """A `package` is either a preset buy-package key (water, rebar, …), the
    document id of a hand-built custom BOM, or the document id of a subcontractor
    trade scope on this project. Custom BOMs and trade scopes are searched and
    quoted exactly like packages, using their doc id as the key."""
    if (
        packages.is_valid(package)
        or documents_repo.is_custom_bom(db, org_id, project_id, package)
        or documents_repo.is_trade_scope(db, org_id, project_id, package)
    ):
        return
    raise HTTPException(status_code=400, detail=f"Unknown package '{package}'")


def _custom_bom(db: Session, org_id: str, project_id: str, package: str):
    """The custom BOM document when `package` names one on this project, else None."""
    if documents_repo.is_custom_bom(db, org_id, project_id, package):
        return documents_repo.get(db, org_id, package)
    return None


def _trade_scope(db: Session, org_id: str, project_id: str, package: str):
    """The trade scope document when `package` names one on this project, else None."""
    if documents_repo.is_trade_scope(db, org_id, project_id, package):
        return documents_repo.get(db, org_id, package)
    return None


def _package_label(db: Session, org_id: str, project_id: str, package: str) -> str:
    """Display label for a package, custom BOM, or trade scope (the doc's name)."""
    bom = _custom_bom(db, org_id, project_id, package)
    if bom is not None:
        return bom.name
    trade = _trade_scope(db, org_id, project_id, package)
    return trade.name if trade is not None else packages.label_for(package)


# --------------------------------------------------------------- supplier search
@router.post(
    "/{project_id}/packages/{package}/search-suppliers",
    response_model=SupplierSearchAccepted,
    status_code=202,
)
def search_suppliers(
    project_id: str,
    package: str,
    payload: SupplierSearchRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    project = _require_project(org_id, project_id, db)
    _require_package(org_id, package, project_id, db)
    audit_repo.log(
        db, org_id, current_user, "supplier_search.started", "package", package,
        project_id=project_id, detail={"radiusMi": payload.radius_mi},
    )

    # A custom BOM has no preset keywords — search on its name (its "description"),
    # mirroring the old free-text ad-hoc search. A trade scope searches on its
    # trade name with installer-oriented keyword variants and a verify hint that
    # steers relevance toward contractors rather than material suppliers. Preset
    # packages pass keywords=None so the service uses their built-in presets.
    keywords: Optional[List[str]] = None
    label: Optional[str] = None
    verify_hint: Optional[str] = None
    bom = _custom_bom(db, org_id, project_id, package)
    trade = _trade_scope(db, org_id, project_id, package)
    if bom is not None:
        keywords = packages.adhoc_keywords(bom.name)
        label = bom.name
    elif trade is not None:
        keywords = packages.trade_keywords(trade.name)
        label = trade.name
        verify_hint = packages.trade_verify_hint(trade.name)

    job = jobs_repo.start(
        db,
        org_id,
        SEARCH_JOB,
        _search_ref(project_id, package),
        {
            "projectId": project_id,
            "package": package,
            "loc": project["loc"],
            "radiusMi": payload.radius_mi,
            "keywords": keywords,
            "label": label,
        },
    )
    background.add_task(
        run_search_job, job["id"], org_id, project_id, project["loc"], package,
        payload.radius_mi, keywords, label, verify_hint,
    )
    return {"status": "searching", "package": package}


def run_search_job(
    job_id: str,
    org_id: str,
    project_id: str,
    loc: str,
    package: str,
    radius_mi: int,
    keywords: Optional[List[str]] = None,
    label: Optional[str] = None,
    verify_hint: Optional[str] = None,
) -> None:
    """Background worker: search + persist. Opens its own DB session.

    ``keywords``/``label`` are set for ad-hoc searches (free-text query);
    otherwise the package presets are used. ``verify_hint`` overrides the
    relevance hint (trade/subcontractor searches). Progress is written to the
    background_jobs row so the poller (and the exception queue) see it.
    ``org_id`` comes from the request that scheduled the job, so the worker's
    own session writes into the same tenant that was authorized.
    """
    db = SessionLocal()
    try:
        cached = sourcing_repo.get_cached_latlng(db, org_id, project_id, loc)
        results, latlng, mocked = sourcing_service.search_suppliers(
            loc, package, radius_mi, cached_latlng=cached, keywords=keywords,
            label=label, verify_hint=verify_hint,
        )
        if latlng is not None and cached is None:
            sourcing_repo.cache_latlng(db, org_id, project_id, loc, latlng[0], latlng[1])
        sourcing_repo.replace_found_suppliers(
            db, org_id, project_id, package, [r.to_dict() for r in results]
        )
        if results:
            events_repo.log(
                db, org_id, project_id,
                title=f"{len(results)} suppliers found",
                icon="supplier", tone="blue",
                meta=f"{label or packages.label_for(package)} · within {radius_mi} mi",
            )
        jobs_repo.finish(db, org_id, job_id, {"mocked": mocked, "found": len(results)})
    except Exception as exc:  # surface the failure to the poller + exception queue
        jobs_repo.fail(db, org_id, job_id, str(exc))
    finally:
        db.close()


_SEARCH_STATUS_MAP = {"running": "searching", "done": "done", "error": "error"}


def _found_suppliers_payload(
    db: Session, org_id: str, project_id: str, package: str
) -> dict:
    """Bucket a project's found suppliers (for one package) into tiers + status."""
    job = jobs_repo.latest(db, org_id, SEARCH_JOB, _search_ref(project_id, package)) or {}
    status_info = dict(job.get("detail") or {})
    if job.get("error"):
        status_info["error"] = job["error"]
    rows = sourcing_repo.list_found_suppliers(db, org_id, project_id, package)

    # Status: prefer the live search status; fall back to done/idle from storage.
    status = _SEARCH_STATUS_MAP.get(job.get("status", ""))
    if status is None:
        status = "done" if rows else "idle"

    # Bucket into tiers for the UI.
    tiers: List[dict] = []
    for tier_num in (1, 2, 3):
        suppliers = [r for r in rows if r.get("tier") == tier_num]
        if suppliers:
            tiers.append(
                {"tier": tier_num, "label": distance.tier_label(tier_num), "suppliers": suppliers}
            )

    return {
        "status": status,
        "mocked": status_info.get("mocked", False),
        "radiusMi": status_info.get("radiusMi", 0),
        "package": package,
        "error": status_info.get("error"),
        "tiers": tiers,
    }


@router.get(
    "/{project_id}/suppliers/found",
    response_model=SupplierSearchResult,
)
def get_found_suppliers(
    project_id: str,
    package: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    _require_package(org_id, package, project_id, db)
    return _found_suppliers_payload(db, org_id, project_id, package)


# --------------------------------------------------------------- quote ingest
@router.post(
    "/{project_id}/quotes/ingest",
    response_model=QuoteIngestResult,
    status_code=202,
)
def ingest_quotes(
    project_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kick off reading supplier quote replies for a project (background task).

    The frontend then polls GET .../quotes/ingest-status until it leaves
    'ingesting', then refreshes the quotes table + comparison.
    """
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    audit_repo.log(
        db, org_id, current_user, "quotes.ingest_started", "project", project_id,
        project_id=project_id,
    )
    job = jobs_repo.start(db, org_id, INGEST_JOB, project_id, {"projectId": project_id})
    background.add_task(run_ingest_job, job["id"], org_id, project_id)
    return {"status": "ingesting", "ingested": 0, "total": 0}


def run_ingest_job(job_id: str, org_id: str, project_id: str) -> None:
    db = SessionLocal()
    try:
        ingested, total, mocked = quotes_ingest.ingest_quotes(db, org_id, project_id)
        if ingested:
            events_repo.log(
                db, org_id, project_id,
                title=f"{ingested} quote{'s' if ingested != 1 else ''} received",
                icon="quote", tone="violet",
                meta="Parsed from supplier replies",
            )
        jobs_repo.finish(
            db, org_id, job_id, {"mocked": mocked, "ingested": ingested, "total": total}
        )
    except Exception as exc:  # surface to the poller + exception queue
        jobs_repo.fail(db, org_id, job_id, str(exc))
    finally:
        db.close()


_INGEST_STATUS_MAP = {"running": "ingesting", "done": "done", "error": "error"}


@router.get(
    "/{project_id}/quotes/ingest-status",
    response_model=QuoteIngestResult,
)
def get_ingest_status(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    job = jobs_repo.latest(db, org_id, INGEST_JOB, project_id)
    if job is None:
        return {"status": "idle", "ingested": 0, "total": 0}
    detail = job.get("detail") or {}
    return {
        "status": _INGEST_STATUS_MAP.get(job.get("status", ""), "idle"),
        "mocked": detail.get("mocked", False),
        "ingested": detail.get("ingested", 0),
        "total": detail.get("total", 0),
        "error": job.get("error"),
    }


# --------------------------------------------------------------- RFQ generation
def _line_items_for_package(
    db: Session, org_id: str, project_id: str, package: str, approved_only: bool = True
) -> Tuple[List[dict], bool, int]:
    """Pull the BOM line items for a package from the project's extracted documents.

    Aggregates the extracted BOM groups across every document on the project,
    keeps the groups whose label maps to this buy-package, and dedupes items by
    name. Falls back to the shared seed BOM if the project has no extracted items
    yet (e.g. the prototype Riverside project / offline mode).

    Approval gate: with ``approved_only`` (the default), only documents whose
    BOM a human has confirmed (reviewed=True) contribute items — unapproved
    extraction output never reaches suppliers.

    Returns ``(items, seeded, pending_review)`` — `seeded` is True when the
    items came from the shared demo BOM; `pending_review` counts the project
    documents that DO have items for this package but are still unconfirmed.
    """
    items: List[dict] = []
    seen: set = set()

    def _matching_items(groups: List[dict]) -> List[dict]:
        out = []
        for group in groups or []:
            if packages.category_for_label(group.get("group", "")) != package:
                continue
            out.extend(group.get("items", []))
        return out

    def _add(candidates: List[dict]) -> None:
        for it in candidates:
            key = (it.get("n") or it.get("name") or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                items.append(it)

    # A custom BOM is its own bill of materials: take its items directly (across
    # all its groups), rather than mapping discipline group labels to a package.
    if documents_repo.is_custom_bom(db, org_id, project_id, package):
        bom = documents_repo.get(db, org_id, package)
        if approved_only and bom is not None and not bom.reviewed:
            return [], False, 1
        for group in documents_repo.get_line_items(db, org_id, package) or []:
            _add(group.get("items", []))
        return items, False, 0

    pending_review = 0
    for doc in documents_repo.list_for_project(db, org_id, project_id):
        doc_items = _matching_items(
            documents_repo.get_line_items(db, org_id, doc.get("id", "")) or []
        )
        if not doc_items:
            continue
        if approved_only and not doc.get("reviewed"):
            pending_review += 1
            continue
        _add(doc_items)

    if items or pending_review:
        return items, False, pending_review

    # nothing extracted for this package yet → prototype demo BOM
    _add(_matching_items(reference_repo.list_line_item_groups(db)))
    return items, True, 0


@router.get(
    "/{project_id}/packages/{package}/bom",
    response_model=PackageBom,
)
def get_package_bom(
    project_id: str,
    package: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The BOM line items this buy-package will ask suppliers to quote.

    Powers the supplier page's "what are we asking for" panel — selecting a
    package (e.g. Water) shows the exact items pulled from the project's
    extracted plans for that discipline. For a custom BOM the items come straight
    from that hand-built document.
    """
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    _require_package(org_id, package, project_id, db)

    bom = _custom_bom(db, org_id, project_id, package)
    items, seeded, pending = _line_items_for_package(db, org_id, project_id, package)
    return {
        "package": package,
        "label": bom.name if bom is not None else packages.label_for(package),
        "tone": "blue" if bom is not None else packages.tone_for(package),
        "count": len(items),
        "items": [
            {"n": it.get("n") or it.get("name") or "", "q": it.get("q") or ""}
            for it in items
        ],
        "seeded": seeded,
        "custom": bom is not None,
        "pendingReview": pending,
    }


@router.get("/{project_id}/boms", response_model=List[CustomBomSummary])
def list_project_boms(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The project's hand-built custom BOMs — the selectable custom packages in
    the supplier search. Each BOM's document id doubles as its package key."""
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    out: List[dict] = []
    for doc in documents_repo.list_custom_boms(db, org_id, project_id):
        groups = documents_repo.get_line_items(db, org_id, doc.id) or []
        count = sum(len(g.get("items", [])) for g in groups)
        out.append(
            {"id": doc.id, "name": doc.name, "count": count, "reviewed": doc.reviewed}
        )
    return out


# --------------------------------------------------------------- trade scopes
def _trade_scope_summary(doc) -> dict:
    return {"id": doc.id, "name": doc.name, "scope": doc.summary or ""}


@router.get("/{project_id}/trades", response_model=List[TradeScopeSummary])
def list_trade_scopes(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The project's subcontractor trade scopes — the selectable trade packages
    in the supplier search. Each scope's document id doubles as its package key."""
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    return [
        _trade_scope_summary(doc)
        for doc in documents_repo.list_trade_scopes(db, org_id, project_id)
    ]


@router.post(
    "/{project_id}/trades", response_model=TradeScopeSummary, status_code=201
)
def create_trade_scope(
    project_id: str,
    payload: TradeScopeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a subcontractor trade scope — a free-text trade the user wants
    bids for (e.g. "Concrete flatwork"), with a scope-of-work description.

    Like a custom BOM there is no file and no extraction: the document id
    becomes a package key, so the trade flows through the same search → select
    → RFQ pipeline. The RFQ it generates is a bid request built from the scope
    text rather than BOM line items.
    """
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    name = payload.name.strip() or "Trade"
    doc = documents_repo.add(
        db,
        org_id=org_id,
        name=name,
        doc_type="Trade Scope",
        pages=0,
        plan_type=documents_repo.TRADE_SCOPE_PLAN_TYPE,
        date=datetime.now().strftime("%b %d, %Y"),
        project_id=project_id,
        has_file=False,
        status="Draft",
        status_tone="gray",
    )
    scope = (payload.scope or "").strip()
    if scope:
        doc = documents_repo.update_status(db, org_id, doc.id, summary=scope)
    audit_repo.log(
        db, org_id, current_user, "trade_scope.created", "document", doc.id,
        project_id=project_id, detail={"name": name},
    )
    events_repo.log(
        db, org_id, project_id,
        title=f"Trade scope created — {name}",
        icon="file", tone="blue",
        meta="Subcontractor trade",
    )
    return _trade_scope_summary(doc)


@router.put("/{project_id}/trades/{trade_id}", response_model=TradeScopeSummary)
def update_trade_scope(
    project_id: str,
    trade_id: str,
    payload: TradeScopeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a trade scope's scope-of-work description."""
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    if not documents_repo.is_trade_scope(db, org_id, project_id, trade_id):
        raise HTTPException(status_code=404, detail="Trade scope not found")
    doc = documents_repo.update_status(
        db, org_id, trade_id, summary=(payload.scope or "").strip()
    )
    if doc is None:  # deleted between the check and the write
        raise HTTPException(status_code=404, detail="Trade scope not found")
    audit_repo.log(
        db, org_id, current_user, "trade_scope.edited", "document", trade_id,
        project_id=project_id, detail={"name": doc.name},
    )
    return _trade_scope_summary(doc)


@router.post(
    "/{project_id}/packages/{package}/rfqs/generate",
    response_model=PersistedRfq,
    status_code=201,
)
def generate_rfq(
    project_id: str,
    package: str,
    payload: RfqGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    project = _require_project(org_id, project_id, db)
    _require_package(org_id, package, project_id, db)
    label = _package_label(db, org_id, project_id, package)

    # Recipients can be freshly-discovered suppliers or ones already saved to the
    # customer's network. Resolve found suppliers first, then fill any remaining
    # ids from the supplier directory so a saved supplier can be RFQ'd directly.
    suppliers = sourcing_repo.get_found_suppliers_by_ids(db, org_id, payload.supplier_ids)
    resolved = {s.get("id") for s in suppliers}
    for sid in payload.supplier_ids:
        if sid in resolved:
            continue
        saved = suppliers_repo.get_supplier(db, org_id, sid)
        if saved:
            suppliers.append(saved)
            resolved.add(sid)
    if not suppliers:
        raise HTTPException(status_code=400, detail="No matching suppliers")

    # A trade scope generates a scope-of-work bid request instead of a BOM
    # quote. The line-items approval gate doesn't apply (there are no extracted
    # items — the scope is human-authored by definition); a non-empty scope is
    # required instead. The bypass is keyed strictly on is_trade_scope so
    # custom BOMs keep the full approval gate.
    trade = _trade_scope(db, org_id, project_id, package)
    if trade is not None:
        scope = (payload.scope or "").strip() or (trade.summary or "").strip()
        if not scope:
            raise HTTPException(
                status_code=400,
                detail="Add a scope of work before generating the bid request",
            )
        if scope != (trade.summary or "").strip():
            # Keep the chip's stored scope in sync with what was actually sent.
            documents_repo.update_status(db, org_id, package, summary=scope)
        draft = rfq_generator.generate_sub_rfq_draft(
            project, label, scope, suppliers, buyer=current_user
        )
        kind = "subcontractor"
    else:
        # Approval gate: an RFQ only ever quotes human-confirmed BOM items.
        line_items, _seeded, pending = _line_items_for_package(
            db, org_id, project_id, package, approved_only=True
        )
        if not line_items:
            detail = (
                f"No approved BOM items for this package — confirm the extracted BOM "
                f"on {pending} document{'s' if pending != 1 else ''} first"
                if pending
                else "No approved BOM items for this package"
            )
            raise HTTPException(status_code=409, detail=detail)
        draft = rfq_generator.generate_rfq_draft(
            project, label, line_items, suppliers, buyer=current_user
        )
        kind = "materials"
    if not draft.recipients:
        raise HTTPException(
            status_code=400,
            detail="None of the selected suppliers have a discovered email",
        )
    rfq = rfqs_repo.create_rfq_draft(
        db,
        org_id,
        project_id=project_id,
        package=package,
        package_label=label,
        subject=draft.subject,
        body=draft.body,
        line_items=draft.line_items,
        recipients=draft.recipients,
        kind=kind,
    )
    audit_repo.log(
        db, org_id, current_user, "rfq.drafted", "rfq", rfq["id"], project_id=project_id,
        detail={
            "package": package,
            "recipients": [r.get("email") for r in draft.recipients],
            "lineItems": len(draft.line_items),
        },
    )
    events_repo.log(
        db, org_id, project_id,
        title=f"RFQ drafted — {label}",
        icon="rfq", tone="ai",
        meta=f"{len(draft.recipients)} supplier{'s' if len(draft.recipients) != 1 else ''}",
    )
    return rfq


@router.get("/{project_id}/rfqs/generated", response_model=List[PersistedRfq])
def list_generated_rfqs(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    return rfqs_repo.list_rfqs(db, org_id, project_id)


@router.get("/{project_id}/rfqs/{rfq_id}", response_model=PersistedRfq)
def get_generated_rfq(
    project_id: str,
    rfq_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    rfq = rfqs_repo.get_rfq(db, org_id, rfq_id)
    if rfq is None or rfq["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return rfq


@router.get("/{project_id}/rfqs/{rfq_id}/conversation", response_model=RfqConversation)
def get_rfq_conversation(
    project_id: str,
    rfq_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full email thread for an RFQ, read live from Gmail when configured.

    Read-only: we surface the original Gmail thread (our outbound plus any
    threaded supplier replies) without changing the RFQ's status.
    """
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    rfq = rfqs_repo.get_rfq(db, org_id, rfq_id)
    if rfq is None or rfq["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    conv = rfq_conversation.build_conversation(db, org_id, rfq)
    return {"rfqId": rfq_id, **conv}


@router.delete("/{project_id}/rfqs/{rfq_id}", status_code=204)
def delete_generated_rfq(
    project_id: str,
    rfq_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    existing = rfqs_repo.get_rfq(db, org_id, rfq_id)
    if existing is None or existing["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    rfqs_repo.delete_rfq(db, org_id, rfq_id)
    audit_repo.log(
        db, org_id, current_user, "rfq.deleted", "rfq", rfq_id, project_id=project_id,
        detail={"status": existing["status"], "package": existing.get("package", "")},
    )
    return Response(status_code=204)


# Total attachment budget per email. Gmail's nominal limit is 25 MB, but the
# raw payload is base64 (~37% inflation) and large JSON `{"raw": ...}` sends via
# the google-api-python-client are unreliable well below that — 15 MB of source
# files keeps the encoded message comfortably inside. Switching to a media
# upload is the escape hatch if bigger attachments are ever needed.
_MAX_ATTACHMENT_TOTAL_BYTES = 15 * 1024 * 1024


def _resolve_attachments(
    db: Session, org_id: str, project_id: str, attachment_ids: List[str]
) -> List[dict]:
    """Validate user-chosen attachment document ids → stored {documentId, name}.

    Each id must be a document in this org and project that actually has a
    stored file; the combined size must fit the email budget. 400 otherwise.
    """
    out: List[dict] = []
    total = 0
    seen: set = set()
    for doc_id in attachment_ids:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        doc = documents_repo.get(db, org_id, doc_id)
        if doc is None or doc.project_id != project_id:
            raise HTTPException(
                status_code=400, detail="Attachment document not found on this project"
            )
        # One storage.size() covers existence AND size (a single stat / S3 HEAD).
        # None means the file is missing or its size can't be determined — either
        # way it must not silently count as 0 bytes against the budget.
        size = storage.size(doc.source_path) if doc.has_file else None
        if size is None:
            raise HTTPException(
                status_code=400,
                detail=f"'{doc.name}' has no attachable file",
            )
        total += size
        if total > _MAX_ATTACHMENT_TOTAL_BYTES:
            limit_mb = _MAX_ATTACHMENT_TOTAL_BYTES // (1024 * 1024)
            raise HTTPException(
                status_code=400,
                detail=f"Attachments exceed the {limit_mb} MB email limit — remove some files",
            )
        out.append({"documentId": doc.id, "name": doc.name})
    return out


@router.put("/{project_id}/rfqs/{rfq_id}", response_model=PersistedRfq)
def update_generated_rfq(
    project_id: str,
    rfq_id: str,
    payload: RfqUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    existing = rfqs_repo.get_rfq(db, org_id, rfq_id)
    if existing is None or existing["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    if existing["status"] not in rfq_state.EDITABLE:
        raise HTTPException(
            status_code=409,
            detail=f"RFQ can no longer be edited (status: {existing['status']})",
        )
    attachments = (
        _resolve_attachments(db, org_id, project_id, payload.attachment_ids)
        if payload.attachment_ids is not None
        else None
    )
    updated = rfqs_repo.update_rfq(
        db,
        org_id,
        rfq_id,
        subject=payload.subject,
        body=payload.body,
        recipients=[r.model_dump() for r in payload.recipients],
        attachments=attachments,
    )
    audit_repo.log(
        db, org_id, current_user, "rfq.edited", "rfq", rfq_id, project_id=project_id,
        detail={
            "recipients": [r.email for r in payload.recipients],
            **(
                {"attachments": [a["name"] for a in attachments]}
                if attachments is not None
                else {}
            ),
        },
    )
    return updated


@router.post("/{project_id}/rfqs/{rfq_id}/send", response_model=PersistedRfq)
def send_generated_rfq(
    project_id: str,
    rfq_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send (or retry) an RFQ. Idempotent and duplicate-safe:

    - Only a Draft or 'Send failed' RFQ can be sent (409 otherwise), so a
      double-click or replayed request never re-emails suppliers.
    - Recipients who already received the RFQ successfully are always skipped;
      a retry only attempts the failed/unsent ones.
    """
    org_id = current_user.organization_id
    _require_project(org_id, project_id, db)
    rfq = rfqs_repo.get_rfq(db, org_id, rfq_id)
    if rfq is None or rfq["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    if rfq["status"] not in rfq_state.SENDABLE:
        raise HTTPException(
            status_code=409,
            detail=f"RFQ was already sent (status: {rfq['status']})",
        )

    recipients = rfq["recipients"]
    if not recipients:
        raise HTTPException(status_code=400, detail="RFQ has no recipients")
    to_send = [r for r in recipients if not rfq_state.recipient_sent(r)]
    if not to_send:
        # Every recipient already has a successful send on record (e.g. the
        # status flip itself failed last time) — just reconcile the status.
        return rfqs_repo.mark_rfq_sent(db, org_id, rfq_id, recipients, status="Awaiting")

    # Hydrate the chosen attachments once (bytes reused for every recipient).
    # A document deleted since the RFQ was saved is skipped rather than fatal —
    # the send still goes out, the skip is recorded in the audit entry, and the
    # RFQ's stored attachment list is trimmed so the UI never shows a document
    # as attached when recipients didn't receive it.
    email_attachments: List[rfq_sender.EmailAttachment] = []
    sent_attachments: List[dict] = []
    skipped_attachments: List[str] = []
    for att in rfq.get("attachments") or []:
        doc = documents_repo.get(db, org_id, att.get("documentId", ""))
        if (
            doc is None
            or doc.project_id != project_id
            or not doc.has_file
            or not storage.exists(doc.source_path)
        ):
            skipped_attachments.append(att.get("name") or att.get("documentId", ""))
            continue
        try:
            with storage.local_copy(doc.source_path) as path:
                with open(path, "rb") as fh:
                    content = fh.read()
        except Exception:
            # A transient storage failure (S3 blip between exists() and the
            # download) must not 500 the whole send — same skip semantics as a
            # deleted document, recorded in the audit detail below.
            skipped_attachments.append(att.get("name") or att.get("documentId", ""))
            continue
        # A dot in the display name isn't necessarily an extension ("Rev 2.1
        # Plans") — only a short alphanumeric suffix counts. Names without one
        # borrow the stored file's suffix so mail clients can type the file.
        source_ext = os.path.splitext(os.path.basename(doc.source_path or ""))[1]
        has_real_ext = bool(re.search(r"\.[A-Za-z0-9]{1,5}$", doc.name))
        filename = doc.name if has_real_ext else f"{doc.name}{source_ext}"
        email_attachments.append(
            rfq_sender.EmailAttachment(filename=filename, content=content)
        )
        sent_attachments.append(att)
    # Save-time validation sized the files then; re-check the actual hydrated
    # bytes so content that grew since save can't push the payload past Gmail.
    if sum(len(a.content) for a in email_attachments) > _MAX_ATTACHMENT_TOTAL_BYTES:
        limit_mb = _MAX_ATTACHMENT_TOTAL_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"Attachments exceed the {limit_mb} MB email limit — remove some files",
        )
    if skipped_attachments:
        rfqs_repo.set_attachments(db, org_id, rfq_id, sent_attachments)

    sender = rfq_sender.get_sender()
    # Always the workspace mailbox (with the sender's name/company as the display
    # name) — see services/rfq/sender.py. The user's own address is Cc'd so they
    # keep a copy, while supplier replies still return to the mailbox quote
    # ingest reads.
    from_addr = rfq_sender.from_header(current_user)
    cc = current_user.cc_email
    # Only pass the attachments kwarg when there is something to attach, so the
    # attachment-free path (and any EmailSender built against the pre-attachment
    # signature) behaves exactly as before.
    send_kwargs = {"attachments": email_attachments} if email_attachments else {}
    for r in to_send:
        try:
            sent = sender.send(r["email"], rfq["subject"], rfq["body"],
                               from_addr=from_addr, cc=cc, **send_kwargs)
            r["sentMessageId"] = sent.message_id
            r["threadId"] = sent.thread_id
            r["sendStatus"] = "sent"
            r["sendError"] = None
        except Exception as exc:  # record the failure per-recipient, keep going
            r["sendStatus"] = "failed"
            r["sendError"] = str(exc)

    failed = [r for r in recipients if not rfq_state.recipient_sent(r)]
    status = "Send failed" if failed else "Awaiting"
    sent_rfq = rfqs_repo.mark_rfq_sent(db, org_id, rfq_id, recipients, status=status)
    delivered = len(recipients) - len(failed)
    audit_repo.log(
        db, org_id, current_user, "rfq.sent", "rfq", rfq_id, project_id=project_id,
        detail={
            "attempted": [r["email"] for r in to_send],
            "delivered": delivered,
            "failed": [{"email": r["email"], "error": r.get("sendError")} for r in failed],
            "from": rfq_sender.from_display(current_user),
            "cc": cc,
            "mock": type(sender).__name__ == "MockSender",
            "attachments": [a.filename for a in email_attachments],
            "skippedAttachments": skipped_attachments,
        },
    )
    events_repo.log(
        db, org_id, project_id,
        title=(
            f"RFQ sent to {delivered} supplier{'s' if delivered != 1 else ''}"
            + (f" — {len(failed)} failed" if failed else "")
        ),
        icon="rfq", tone="danger" if failed else "success",
        meta=rfq.get("pkg") or rfq.get("subject", ""),
    )
    return sent_rfq
