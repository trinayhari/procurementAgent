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
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
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
from app.services import extraction
from app.services.extraction import isolated as extraction_isolated
from app.services.extraction import pdf

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)


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
    return doc.to_dict()


@router.get("/{document_id}/file")
def get_document_file(document_id: str, db: Session = Depends(get_db)):
    """Serve the original uploaded file inline so the frontend can preview it.

    Only uploaded documents have a `source_path` on disk; seed/demo docs return
    404 and the UI falls back to its placeholder."""
    doc = documents_repo.get(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = doc.source_path
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No previewable file for this document")
    filename = os.path.basename(path)
    media_type = "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/{document_id}/line-items", response_model=List[LineItemGroup])
def get_document_line_items(document_id: str, db: Session = Depends(get_db)):
    """BOM groups extracted from one document."""
    if documents_repo.get(db, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    groups = documents_repo.get_line_items(db, document_id)
    return groups or []


@router.put("/{document_id}/line-items", response_model=List[LineItemGroup])
def save_document_line_items(document_id: str, payload: LineItemsUpdate, db: Session = Depends(get_db)):
    """Human-in-the-loop: replace a document's BOM with the reviewer's edits.

    Recomputes group counts and the document's item total, and flags it as edited.
    """
    if documents_repo.get(db, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    groups = [g.model_dump() for g in payload.groups]
    return documents_repo.save_line_items(db, document_id, groups)


@router.post("/{document_id}/confirm", response_model=Document)
def confirm_document(document_id: str, db: Session = Depends(get_db)):
    """Human-in-the-loop: mark a document's BOM as reviewed and approved."""
    doc = documents_repo.confirm(db, document_id, datetime.now().strftime("%b %d, %Y"))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc.to_dict()


@router.post("/manual", response_model=Document, status_code=201)
def create_manual_bom(payload: ManualBomCreate, db: Session = Depends(get_db)):
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
def delete_document(document_id: str, db: Session = Depends(get_db)):
    """Delete a document, its extracted BOM, and any uploaded source file."""
    deleted = documents_repo.delete(db, document_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return None


@router.post("", response_model=Document, status_code=201)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    plan_type: str = Form(default=None),
    project_id: str = Form(default="riverside"),
    db: Session = Depends(get_db),
):
    """Upload a plan set and kick off background AI extraction. The document is
    attached to `project_id` so each project keeps its own document list."""
    plan_type = plan_type or extraction.registry.default_key()
    spec = extraction.registry.get(plan_type)
    if spec is None or not spec.enabled:
        raise HTTPException(status_code=400, detail=f"Unsupported or disabled plan type '{plan_type}'")

    os.makedirs(settings.upload_dir, exist_ok=True)
    safe_name = os.path.basename(file.filename or "document")
    dest = os.path.join(settings.upload_dir, safe_name)

    # Stream the upload to disk in chunks rather than reading it all into memory.
    # Plan sets can be ~100MB; a full read held the whole file in RAM (twice, with
    # the write buffer) on top of the resident app — enough to OOM a small
    # container before extraction even started.
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    with open(dest, "wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                fh.close()
                os.remove(dest)
                raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb}MB limit")
            fh.write(chunk)

    try:
        pages = pdf.page_count(dest)
    except pdf.UnsupportedDocument:
        pages = 0

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
        source_path=dest,
        has_file=True,
        status="Processing" if analyzable else "Analyzed",
        status_tone="blue" if analyzable else "success",
    )
    payload = doc.to_dict()
    events_repo.log(
        db,
        project_id,
        title=f"{'Plans' if extractable else 'Document'} uploaded — {payload['name']}",
        icon="file",
        tone="blue",
        meta=f"{spec.label}{f' · {pages} pages' if pages else ''}",
    )
    if analyzable:
        background.add_task(_run_pipeline, doc.id, dest, plan_type)
    return payload


@router.post("/{document_id}/analyze", response_model=Document)
def analyze_document(document_id: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Re-run extraction (BOM and timeline) for an already-uploaded document."""
    doc = documents_repo.get(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    plan_type = doc.plan_type
    path = doc.source_path
    if not plan_type or not path or not os.path.exists(path):
        raise HTTPException(status_code=409, detail="Document has no source file to re-analyze")
    spec = extraction.registry.get(plan_type)
    if spec is None:
        raise HTTPException(status_code=409, detail="This document type cannot be analyzed")
    documents_repo.update_status(db, document_id, status="Processing", status_tone="blue", processing=True)
    background.add_task(_run_pipeline, document_id, path, plan_type)
    return documents_repo.get(db, document_id).to_dict()


def _run_pipeline(document_id: str, path: str, plan_type: str) -> None:
    """Background worker: run timeline extraction, then BOM extraction.

    Timeline runs FIRST (it's one cheap text call) so that when the BOM pass
    writes the document's terminal status — the signal the frontend polls on —
    everything, timeline included, is already in the database and one reload
    picks it all up. Document types with no BOM categories (additional
    documents) get their terminal status here instead.
    """
    _run_timeline_extraction(document_id, path)
    spec = extraction.registry.get(plan_type)
    if spec is not None and spec.categories:
        _run_extraction(document_id, path, plan_type)
    else:
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
