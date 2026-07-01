"""Supplier search + RFQ generation/sending for a project's buy-packages.

Search runs as a background task (geocode → Places → website email scrape is slow)
and the frontend polls GET .../suppliers/found, mirroring the document-extraction
UX. With no Google/Gmail keys the whole flow runs against mocks.
"""
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.repositories import documents as documents_repo
from app.repositories import events as events_repo
from app.repositories import projects as projects_repo
from app.repositories import reference as reference_repo
from app.repositories import rfqs as rfqs_repo
from app.repositories import sourcing as sourcing_repo
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
)
from app.services.quotes import ingest as quotes_ingest
from app.services.rfq import conversation as rfq_conversation
from app.services.rfq import generator as rfq_generator
from app.services.rfq import sender as rfq_sender
from app.services.sourcing import distance, packages
from app.services.sourcing import service as sourcing_service

router = APIRouter(prefix="/api/projects", tags=["sourcing"])

# Transient per-(project, package) search status — same approach as document
# 'Processing' state. Keyed by (project_id, package).
_SEARCH_STATUS: Dict[Tuple[str, str], dict] = {}

# Transient per-project quote-ingest status (mirrors the search status pattern).
_INGEST_STATUS: Dict[str, dict] = {}


def _require_project(project_id: str, db: Session) -> dict:
    project = projects_repo.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _require_package(package: str, project_id: str, db: Session) -> None:
    """A `package` is either a preset buy-package key (water, rebar, …) or the
    document id of a hand-built custom BOM on this project. Custom BOMs are
    searched and quoted exactly like packages, using their doc id as the key."""
    if packages.is_valid(package) or documents_repo.is_custom_bom(db, project_id, package):
        return
    raise HTTPException(status_code=400, detail=f"Unknown package '{package}'")


def _custom_bom(db: Session, project_id: str, package: str):
    """The custom BOM document when `package` names one on this project, else None."""
    if documents_repo.is_custom_bom(db, project_id, package):
        return documents_repo.get(db, package)
    return None


def _package_label(db: Session, project_id: str, package: str) -> str:
    """Display label for a package or custom BOM (the BOM's own name)."""
    bom = _custom_bom(db, project_id, package)
    return bom.name if bom is not None else packages.label_for(package)


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
):
    project = _require_project(project_id, db)
    _require_package(package, project_id, db)

    # A custom BOM has no preset keywords — search on its name (its "description"),
    # mirroring the old free-text ad-hoc search. Preset packages pass keywords=None
    # so the service uses their built-in query presets.
    keywords: Optional[List[str]] = None
    label: Optional[str] = None
    bom = _custom_bom(db, project_id, package)
    if bom is not None:
        keywords = packages.adhoc_keywords(bom.name)
        label = bom.name

    _SEARCH_STATUS[(project_id, package)] = {"status": "searching", "radiusMi": payload.radius_mi}
    background.add_task(
        _run_search, project_id, project["loc"], package, payload.radius_mi, keywords, label
    )
    return {"status": "searching", "package": package}


def _run_search(
    project_id: str,
    loc: str,
    package: str,
    radius_mi: int,
    keywords: Optional[List[str]] = None,
    label: Optional[str] = None,
) -> None:
    """Background worker: search + persist. Opens its own DB session.

    ``keywords``/``label`` are set for ad-hoc searches (free-text query);
    otherwise the package presets are used.
    """
    key = (project_id, package)
    db = SessionLocal()
    try:
        cached = sourcing_repo.get_cached_latlng(db, project_id, loc)
        results, latlng, mocked = sourcing_service.search_suppliers(
            loc, package, radius_mi, cached_latlng=cached, keywords=keywords, label=label
        )
        if latlng is not None and cached is None:
            sourcing_repo.cache_latlng(db, project_id, loc, latlng[0], latlng[1])
        sourcing_repo.replace_found_suppliers(
            db, project_id, package, [r.to_dict() for r in results]
        )
        if results:
            events_repo.log(
                db, project_id,
                title=f"{len(results)} suppliers found",
                icon="supplier", tone="blue",
                meta=f"{label or packages.label_for(package)} · within {radius_mi} mi",
            )
        _SEARCH_STATUS[key] = {"status": "done", "radiusMi": radius_mi, "mocked": mocked}
    except Exception as exc:  # surface the failure to the poller
        _SEARCH_STATUS[key] = {"status": "error", "radiusMi": radius_mi, "error": str(exc)}
    finally:
        db.close()


def _found_suppliers_payload(db: Session, project_id: str, package: str) -> dict:
    """Bucket a project's found suppliers (for one package) into tiers + status."""
    status_info = _SEARCH_STATUS.get((project_id, package), {})
    rows = sourcing_repo.list_found_suppliers(db, project_id, package)

    # Status: prefer the live search status; fall back to done/idle from storage.
    status = status_info.get("status")
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
):
    _require_project(project_id, db)
    _require_package(package, project_id, db)
    return _found_suppliers_payload(db, project_id, package)


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
):
    """Kick off reading supplier quote replies for a project (background task).

    The frontend then polls GET .../quotes/ingest-status until it leaves
    'ingesting', then refreshes the quotes table + comparison.
    """
    _require_project(project_id, db)
    _INGEST_STATUS[project_id] = {"status": "ingesting", "ingested": 0, "total": 0}
    background.add_task(_run_ingest, project_id)
    return {"status": "ingesting", "ingested": 0, "total": 0}


def _run_ingest(project_id: str) -> None:
    db = SessionLocal()
    try:
        ingested, total, mocked = quotes_ingest.ingest_quotes(db, project_id)
        if ingested:
            events_repo.log(
                db, project_id,
                title=f"{ingested} quote{'s' if ingested != 1 else ''} received",
                icon="quote", tone="violet",
                meta="Parsed from supplier replies",
            )
        _INGEST_STATUS[project_id] = {
            "status": "done",
            "mocked": mocked,
            "ingested": ingested,
            "total": total,
        }
    except Exception as exc:  # surface to the poller
        _INGEST_STATUS[project_id] = {"status": "error", "error": str(exc)}
    finally:
        db.close()


@router.get(
    "/{project_id}/quotes/ingest-status",
    response_model=QuoteIngestResult,
)
def get_ingest_status(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    info = _INGEST_STATUS.get(project_id)
    if info is None:
        return {"status": "idle", "ingested": 0, "total": 0}
    return {
        "status": info.get("status", "idle"),
        "mocked": info.get("mocked", False),
        "ingested": info.get("ingested", 0),
        "total": info.get("total", 0),
        "error": info.get("error"),
    }


# --------------------------------------------------------------- RFQ generation
def _line_items_for_package(
    db: Session, project_id: str, package: str
) -> Tuple[List[dict], bool]:
    """Pull the BOM line items for a package from the project's extracted documents.

    Aggregates the extracted BOM groups across every document on the project,
    keeps the groups whose label maps to this buy-package, and dedupes items by
    name. Falls back to the shared seed BOM if the project has no extracted items
    yet (e.g. the prototype Riverside project / offline mode).

    Returns the items plus a `seeded` flag — True when the items came from the
    shared demo BOM rather than this project's own extracted documents.
    """
    items: List[dict] = []
    seen: set = set()

    # A custom BOM is its own bill of materials: take its items directly (across
    # all its groups), rather than mapping discipline group labels to a package.
    if documents_repo.is_custom_bom(db, project_id, package):
        for group in documents_repo.get_line_items(db, package) or []:
            for it in group.get("items", []):
                key = (it.get("n") or it.get("name") or "").strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    items.append(it)
        return items, False

    def _collect(groups: List[dict]) -> None:
        for group in groups or []:
            if packages.category_for_label(group.get("group", "")) != package:
                continue
            for it in group.get("items", []):
                key = (it.get("n") or it.get("name") or "").strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    items.append(it)

    for doc in documents_repo.list_for_project(db, project_id):
        _collect(documents_repo.get_line_items(db, doc.get("id", "")) or [])

    if items:
        return items, False

    # nothing extracted for this package yet → prototype demo BOM
    _collect(reference_repo.list_line_item_groups(db))
    return items, True


@router.get(
    "/{project_id}/packages/{package}/bom",
    response_model=PackageBom,
)
def get_package_bom(
    project_id: str,
    package: str,
    db: Session = Depends(get_db),
):
    """The BOM line items this buy-package will ask suppliers to quote.

    Powers the supplier page's "what are we asking for" panel — selecting a
    package (e.g. Water) shows the exact items pulled from the project's
    extracted plans for that discipline. For a custom BOM the items come straight
    from that hand-built document.
    """
    _require_project(project_id, db)
    _require_package(package, project_id, db)

    bom = _custom_bom(db, project_id, package)
    items, seeded = _line_items_for_package(db, project_id, package)
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
    }


@router.get("/{project_id}/boms", response_model=List[CustomBomSummary])
def list_project_boms(project_id: str, db: Session = Depends(get_db)):
    """The project's hand-built custom BOMs — the selectable custom packages in
    the supplier search. Each BOM's document id doubles as its package key."""
    _require_project(project_id, db)
    out: List[dict] = []
    for doc in documents_repo.list_custom_boms(db, project_id):
        groups = documents_repo.get_line_items(db, doc.id) or []
        count = sum(len(g.get("items", [])) for g in groups)
        out.append(
            {"id": doc.id, "name": doc.name, "count": count, "reviewed": doc.reviewed}
        )
    return out


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
):
    project = _require_project(project_id, db)
    _require_package(package, project_id, db)
    label = _package_label(db, project_id, package)

    suppliers = sourcing_repo.get_found_suppliers_by_ids(db, payload.supplier_ids)
    if not suppliers:
        raise HTTPException(status_code=400, detail="No matching found suppliers")

    line_items, _seeded = _line_items_for_package(db, project_id, package)
    draft = rfq_generator.generate_rfq_draft(project, label, line_items, suppliers)
    if not draft.recipients:
        raise HTTPException(
            status_code=400,
            detail="None of the selected suppliers have a discovered email",
        )
    rfq = rfqs_repo.create_rfq_draft(
        db,
        project_id=project_id,
        package=package,
        package_label=label,
        subject=draft.subject,
        body=draft.body,
        line_items=draft.line_items,
        recipients=draft.recipients,
    )
    events_repo.log(
        db, project_id,
        title=f"RFQ drafted — {label}",
        icon="rfq", tone="ai",
        meta=f"{len(draft.recipients)} supplier{'s' if len(draft.recipients) != 1 else ''}",
    )
    return rfq


@router.get("/{project_id}/rfqs/generated", response_model=List[PersistedRfq])
def list_generated_rfqs(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return rfqs_repo.list_rfqs(db, project_id)


@router.get("/{project_id}/rfqs/{rfq_id}", response_model=PersistedRfq)
def get_generated_rfq(project_id: str, rfq_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    rfq = rfqs_repo.get_rfq(db, rfq_id)
    if rfq is None or rfq["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return rfq


@router.get("/{project_id}/rfqs/{rfq_id}/conversation", response_model=RfqConversation)
def get_rfq_conversation(project_id: str, rfq_id: str, db: Session = Depends(get_db)):
    """Full email thread for an RFQ, read live from Gmail when configured.

    Read-only: we surface the original Gmail thread (our outbound plus any
    threaded supplier replies) without changing the RFQ's status.
    """
    _require_project(project_id, db)
    rfq = rfqs_repo.get_rfq(db, rfq_id)
    if rfq is None or rfq["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    conv = rfq_conversation.build_conversation(db, rfq)
    return {"rfqId": rfq_id, **conv}


@router.delete("/{project_id}/rfqs/{rfq_id}", status_code=204)
def delete_generated_rfq(project_id: str, rfq_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    existing = rfqs_repo.get_rfq(db, rfq_id)
    if existing is None or existing["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    rfqs_repo.delete_rfq(db, rfq_id)
    return Response(status_code=204)


@router.put("/{project_id}/rfqs/{rfq_id}", response_model=PersistedRfq)
def update_generated_rfq(
    project_id: str, rfq_id: str, payload: RfqUpdate, db: Session = Depends(get_db)
):
    _require_project(project_id, db)
    existing = rfqs_repo.get_rfq(db, rfq_id)
    if existing is None or existing["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return rfqs_repo.update_rfq(
        db,
        rfq_id,
        subject=payload.subject,
        body=payload.body,
        recipients=[r.model_dump() for r in payload.recipients],
    )


@router.post("/{project_id}/rfqs/{rfq_id}/send", response_model=PersistedRfq)
def send_generated_rfq(project_id: str, rfq_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    rfq = rfqs_repo.get_rfq(db, rfq_id)
    if rfq is None or rfq["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="RFQ not found")

    sender = rfq_sender.get_sender()
    from_addr = rfq_sender.sender_address()
    recipients = rfq["recipients"]
    if not recipients:
        raise HTTPException(status_code=400, detail="RFQ has no recipients")

    for r in recipients:
        try:
            sent = sender.send(r["email"], rfq["subject"], rfq["body"], from_addr=from_addr)
            r["sentMessageId"] = sent.message_id
            r["threadId"] = sent.thread_id
        except Exception as exc:  # record the failure per-recipient, keep going
            r["sentMessageId"] = f"error: {exc}"

    # Sent → Awaiting (awaiting supplier quotes); the ingest poller flips to Quoted.
    sent_rfq = rfqs_repo.mark_rfq_sent(db, rfq_id, recipients, status="Awaiting")
    delivered = sum(
        1 for r in recipients if not str(r.get("sentMessageId", "")).startswith("error:")
    )
    events_repo.log(
        db, project_id,
        title=f"RFQ sent to {delivered} supplier{'s' if delivered != 1 else ''}",
        icon="rfq", tone="success",
        meta=rfq.get("pkg") or rfq.get("subject", ""),
    )
    return sent_rfq
