"""Document upload, AI extraction, and BOM retrieval.

Upload flow:
  1. POST a file (+ plan_type) → it's saved to the upload dir and a document
     record is created in 'Processing'.
  2. A FastAPI BackgroundTask runs GPT-4.1 vision extraction (see
     app.services.extraction) and writes the resulting BOM groups + status.
  3. The frontend polls GET /api/documents/{id} until it leaves 'Processing',
     then loads GET /api/documents/{id}/line-items.

Documents are persisted to SQLite (see app/models/document.py), so uploads and
their extracted BOMs survive a backend restart.
"""
import logging
import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import create_scoped_token, get_current_user, verify_scoped_token
from app.db import SessionLocal, get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import documents as documents_repo
from app.repositories import events as events_repo
from app.repositories import timeline as timeline_repo
from app.schemas.document import (
    Document,
    LineItemGroup,
    LineItemsUpdate,
    ManualBomCreate,
    PlanType,
)
from app.services import extraction, storage
from app.services.extraction import isolated as extraction_isolated
from app.services.extraction import pdf

router = APIRouter(prefix="/api/documents", tags=["documents"])
# Signed-URL file serving lives on its own router: it's mounted WITHOUT the
# app-wide auth dependency (iframes/downloads can't send an Authorization
# header) and validates a short-lived scoped query token instead.
file_router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)

# File types the upload endpoint accepts (plan sets, schedules, material lists).
_ALLOWED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls", ".png", ".jpg", ".jpeg"}

# Signed file URLs stay valid this long — enough for a preview session.
_FILE_TOKEN_MINUTES = 15


@router.get("/plan-types", response_model=List[PlanType])
def list_plan_types():
    """Plan types the extractor supports — drives the upload selector."""
    return [
        {
            "key": s.key,
            "label": s.label,
            "description": s.description,
            "enabled": s.enabled,
            "categories": [c.label for c in s.categories],
            "singleton": s.singleton,
        }
        for s in extraction.registry.all_specs()
    ]


@router.get("/{document_id}", response_model=Document)
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = documents_repo.get(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    payload = doc.to_dict()
    payload["timelineEvents"] = timeline_repo.count_for_document(db, document_id)
    return payload


@router.get("/{document_id}/file-url")
def get_document_file_url(document_id: str, db: Session = Depends(get_db)):
    """Mint a signed, short-lived URL for previewing/downloading the original file.

    The frontend loads files in an iframe (no Authorization header possible), so
    access is granted via a scoped token bound to this one document."""
    doc = documents_repo.get(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not storage.exists(doc.source_path):
        raise HTTPException(status_code=404, detail="No previewable file for this document")
    token = create_scoped_token(document_id, f"file:{document_id}", _FILE_TOKEN_MINUTES)
    return {"url": f"/api/documents/{document_id}/file?token={token}", "expiresInMinutes": _FILE_TOKEN_MINUTES}


@file_router.get("/{document_id}/file")
def get_document_file(document_id: str, token: str = "", db: Session = Depends(get_db)):
    """Serve the original uploaded file inline, authorized by a signed URL token
    from GET /{id}/file-url. Local storage streams the file; S3 redirects to a
    short-lived presigned URL. Seed/demo docs have no stored file and 404."""
    if not token or verify_scoped_token(token, f"file:{document_id}") is None:
        raise HTTPException(status_code=401, detail="Invalid or expired file token")
    doc = documents_repo.get(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    locator = doc.source_path
    if not storage.exists(locator):
        raise HTTPException(status_code=404, detail="No previewable file for this document")
    ext = os.path.splitext(locator)[1].lower()
    display_name = f"{doc.name}{ext}" if doc.name else os.path.basename(locator)
    return storage.serve(locator, display_name)


@router.get("/{document_id}/line-items", response_model=List[LineItemGroup])
def get_document_line_items(document_id: str, db: Session = Depends(get_db)):
    """BOM groups extracted from one document."""
    if documents_repo.get(db, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    groups = documents_repo.get_line_items(db, document_id)
    return groups or []


@router.put("/{document_id}/line-items", response_model=List[LineItemGroup])
def save_document_line_items(
    document_id: str,
    payload: LineItemsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Human-in-the-loop: replace a document's BOM with the reviewer's edits.

    Recomputes group counts and the document's item total, and flags it as edited.
    """
    doc = documents_repo.get(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    groups = [g.model_dump() for g in payload.groups]
    saved = documents_repo.save_line_items(db, document_id, groups)
    audit_repo.log(
        db, current_user, "bom.edited", "document", document_id,
        project_id=doc.project_id,
        detail={"groups": len(groups), "items": sum(len(g.get("items", [])) for g in groups)},
    )
    return saved


@router.post("/{document_id}/confirm", response_model=Document)
def confirm_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Human-in-the-loop: mark a document's BOM as reviewed and approved."""
    doc = documents_repo.confirm(db, document_id, datetime.now().strftime("%b %d, %Y"))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    audit_repo.log(
        db, current_user, "bom.confirmed", "document", document_id,
        project_id=doc.project_id, detail={"name": doc.name},
    )
    return doc.to_dict()


@router.post("/manual", response_model=Document, status_code=201)
def create_manual_bom(
    payload: ManualBomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a hand-built custom BOM — a bill of materials the user types by hand.

    There's no file and no extraction: it's seeded with one empty group and then
    edited via the same line-items endpoints an extracted BOM uses. It appears in
    the Documents panel and becomes a selectable "package" in the supplier search
    (its document id is used as the package key), replacing the old free-text
    ad-hoc RFQ flow with a saved, viewable bill of materials.
    """
    name = payload.name.strip() or "Custom BOM"
    doc = documents_repo.add(
        db,
        name=name,
        doc_type="Custom BOM",
        pages=0,
        plan_type=documents_repo.CUSTOM_BOM_PLAN_TYPE,
        date=datetime.now().strftime("%b %d, %Y"),
        project_id=payload.projectId,
        has_file=False,
        status="Draft",
        status_tone="gray",
    )
    # Seed one empty group so the editor opens with a place to add items.
    documents_repo.set_line_items(
        db, doc.id, [{"group": name, "count": 0, "tone": "blue", "items": []}]
    )
    documents_repo.update_status(db, doc.id, items="0")
    audit_repo.log(
        db, current_user, "bom.created_manual", "document", doc.id,
        project_id=payload.projectId, detail={"name": name},
    )
    events_repo.log(
        db,
        payload.projectId,
        title=f"Custom BOM created — {name}",
        icon="file",
        tone="blue",
        meta="Manual bill of materials",
    )
    return documents_repo.get(db, doc.id).to_dict()


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document, its extracted BOM, and any uploaded source file."""
    deleted = documents_repo.delete(db, document_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Document not found")
    audit_repo.log(
        db, current_user, "document.deleted", "document", document_id,
        project_id=getattr(deleted, "project_id", None) or None,
        detail={"name": getattr(deleted, "name", "")},
    )
    return None


@router.post("", response_model=Document, status_code=201)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    plan_type: str = Form(default=None),
    project_id: str = Form(default="riverside"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a plan set and kick off background AI extraction. The document is
    attached to `project_id` so each project keeps its own document list."""
    plan_type = plan_type or extraction.registry.default_key()
    spec = extraction.registry.get(plan_type)
    if spec is None or not spec.enabled:
        raise HTTPException(status_code=400, detail=f"Unsupported or disabled plan type '{plan_type}'")

    safe_name = os.path.basename(file.filename or "document")
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or 'none'}' — allowed: "
            + ", ".join(sorted(_ALLOWED_EXTENSIONS)),
        )

    # Stream the upload to a temp file in chunks (hashing as we go) rather than
    # reading it all into memory — plan sets can be ~100MB and a full read
    # could OOM a small container. The file then moves into the configured
    # storage backend (local disk or S3) under a unique, collision-proof name.
    try:
        temp = await storage.stream_upload_to_temp(file, settings.max_upload_mb * 1024 * 1024)
    except storage.UploadTooLarge:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb}MB limit")

    try:
        pages = pdf.page_count(temp.locator)  # temp is always a local path
    except pdf.UnsupportedDocument:
        pages = 0

    stored = storage.persist_temp(temp, safe_name)

    # Single-document slots (site / building / electrical plan) hold one document
    # each — re-uploading that plan type replaces the prior one ("update a slot").
    if spec.singleton:
        documents_repo.delete_for_plan_type(db, project_id, plan_type)

    # "Additional Document" slots have no BOM categories, so there's no BOM to
    # extract — but every renderable document still goes through TIMELINE
    # extraction (schedules/contracts usually arrive as additional documents).
    extractable = bool(spec.categories)
    analyzable = extractable or pages > 0

    doc = documents_repo.add(
        db,
        name=os.path.splitext(safe_name)[0],
        doc_type=spec.label,
        pages=pages,
        plan_type=plan_type,
        date=datetime.now().strftime("%b %d, %Y"),
        project_id=project_id,
        source_path=stored.locator,
        has_file=True,
        status="Processing" if analyzable else "Analyzed",
        status_tone="blue" if analyzable else "success",
        checksum_sha256=stored.sha256,
    )
    payload = doc.to_dict()
    audit_repo.log(
        db, current_user, "document.uploaded", "document", doc.id,
        project_id=project_id,
        detail={
            "name": payload["name"], "planType": plan_type, "pages": pages,
            "bytes": stored.size, "sha256": stored.sha256,
            "storage": storage.backend_name(),
        },
    )
    events_repo.log(
        db,
        project_id,
        title=f"{'Plans' if extractable else 'Document'} uploaded — {payload['name']}",
        icon="file",
        tone="blue",
        meta=f"{spec.label}{f' · {pages} pages' if pages else ''}",
    )
    if analyzable:
        background.add_task(_run_pipeline, doc.id, stored.locator, plan_type)
    return payload


@router.post("/{document_id}/analyze", response_model=Document)
def analyze_document(
    document_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run extraction (BOM and timeline) for an already-uploaded document."""
    doc = documents_repo.get(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    audit_repo.log(
        db, current_user, "document.reanalyzed", "document", document_id,
        project_id=doc.project_id, detail={"name": doc.name},
    )
    plan_type = doc.plan_type
    path = doc.source_path
    if not plan_type or not storage.exists(path):
        raise HTTPException(status_code=409, detail="Document has no source file to re-analyze")
    spec = extraction.registry.get(plan_type)
    if spec is None:
        raise HTTPException(status_code=409, detail="This document type cannot be analyzed")
    documents_repo.update_status(db, document_id, status="Processing", status_tone="blue", processing=True)
    background.add_task(_run_pipeline, document_id, path, plan_type)
    return documents_repo.get(db, document_id).to_dict()


def _run_pipeline(document_id: str, locator: str, plan_type: str) -> None:
    """Background worker: run timeline extraction, then BOM extraction.

    Timeline runs FIRST (it's one cheap text call) so that when the BOM pass
    writes the document's terminal status — the signal the frontend polls on —
    everything, timeline included, is already in the database and one reload
    picks it all up. Document types with no BOM categories (additional
    documents) get their terminal status here instead.

    Extraction (PyMuPDF in a subprocess) needs a filesystem path, so the
    stored file is materialised locally for the duration — a no-op on the
    local backend, a temp download for S3.
    """
    try:
        with storage.local_copy(locator) as path:
            _run_timeline_extraction(document_id, path)
            spec = extraction.registry.get(plan_type)
            if spec is not None and spec.categories:
                _run_extraction(document_id, path, plan_type)
                return
    except Exception as exc:  # e.g. the S3 download failed
        logger.exception("Could not materialise stored file: doc=%s", document_id)
        with SessionLocal() as db:
            documents_repo.update_status(
                db, document_id,
                status="Failed", status_tone="danger", processing=False,
                items="—", error=f"Could not read the stored file: {exc}",
            )
        return
    with SessionLocal() as db:
        documents_repo.update_status(
            db, document_id,
            status="Analyzed", status_tone="success", processing=False,
        )


def _run_timeline_extraction(document_id: str, path: str) -> None:
    """Extract schedule events from one document into the project timeline.

    Best-effort: the timeline is an enrichment, so a failure here never fails
    the document — it is logged and the document continues to BOM extraction.
    On success the document's previous events are replaced (a re-analysis
    refreshes rather than duplicates); on failure existing events are kept.
    """
    logger.info("Timeline extraction started: doc=%s path=%s", document_id, path)
    try:
        result = extraction_isolated.run_timeline(path)
    except Exception:  # noqa: BLE001 — enrichment only, never break the pipeline
        logger.exception("Timeline extraction crashed: doc=%s", document_id)
        return
    if result.error:
        logger.warning("Timeline extraction failed: doc=%s error=%s", document_id, result.error)
        return
    with SessionLocal() as db:
        doc = documents_repo.get(db, document_id)
        if doc is None:
            return
        n = timeline_repo.replace_for_document(db, doc.project_id, document_id, doc.name, result.events)
        logger.info("Timeline extraction complete: doc=%s events=%s", document_id, n)
        if n:
            events_repo.log(
                db, doc.project_id,
                title=f"Timeline extracted — {n} schedule event{'s' if n != 1 else ''}",
                icon="sparkles", tone="ai", meta=doc.name,
            )


def _run_extraction(document_id: str, path: str, plan_type: str) -> None:
    """Background worker: extract BOMs and update the document record.

    Runs after the response is sent, so it opens its own DB session rather than
    reusing the request-scoped one.

    Any unexpected failure is caught and recorded on the document as 'Failed' so
    it never stays stuck in 'Processing' (which would make the frontend poll
    forever and never show a count). The error is also logged so production
    extraction failures are diagnosable.
    """
    logger.info("Extraction started: doc=%s plan=%s path=%s", document_id, plan_type, path)
    try:
        # Run in a child process: PyMuPDF can segfault on some PDFs, which would
        # otherwise take down the whole API. Isolation turns that into a normal
        # exception we record as 'Failed' below.
        result = extraction_isolated.run(path, plan_type)
    except Exception as exc:  # noqa: BLE001 — last-resort guard for the background task
        logger.exception("Extraction crashed: doc=%s", document_id)
        with SessionLocal() as db:
            doc = documents_repo.get(db, document_id)
            if doc is None:
                return
            documents_repo.update_status(
                db, document_id,
                status="Failed", status_tone="danger", processing=False,
                items="—", error=f"Extraction failed: {exc}",
            )
            events_repo.log(
                db, doc.project_id,
                title=f"Extraction failed — {doc.name}",
                icon="alert", tone="danger", meta=str(exc)[:80],
            )
        return

    with SessionLocal() as db:
        doc = documents_repo.get(db, document_id)
        if doc is None:
            return
        documents_repo.set_line_items(db, document_id, result.groups)
        if result.error:
            logger.warning("Extraction failed: doc=%s error=%s", document_id, result.error)
            documents_repo.update_status(
                db, document_id,
                status="Failed", status_tone="danger", processing=False,
                items="—", error=result.error,
            )
            events_repo.log(
                db, doc.project_id,
                title=f"Extraction failed — {doc.name}",
                icon="alert", tone="danger", meta=result.error[:80],
            )
        else:
            documents_repo.update_status(
                db, document_id,
                status="Analyzed", status_tone="success", processing=False,
                items=str(result.total_items), summary=result.summary, mocked=result.mocked,
            )
            logger.info(
                "Extraction complete: doc=%s items=%s mocked=%s",
                document_id, result.total_items, result.mocked,
            )
            events_repo.log(
                db, doc.project_id,
                title=f"BOM extracted — {result.total_items} line items",
                icon="sparkles", tone="ai", meta=doc.name,
            )
