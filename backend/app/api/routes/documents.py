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
import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.repositories import documents as documents_repo
from app.schemas.document import Document, LineItemGroup, LineItemsUpdate, PlanType
from app.services import extraction
from app.services.extraction import pdf

router = APIRouter(prefix="/api/documents", tags=["documents"])


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
    contents = await file.read()
    if len(contents) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb}MB limit")

    safe_name = os.path.basename(file.filename or "document")
    dest = os.path.join(settings.upload_dir, safe_name)
    with open(dest, "wb") as fh:
        fh.write(contents)

    try:
        pages = pdf.page_count(dest)
    except pdf.UnsupportedDocument:
        pages = 0

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
    )
    payload = doc.to_dict()
    background.add_task(_run_extraction, doc.id, dest, plan_type)
    return payload


@router.post("/{document_id}/analyze", response_model=Document)
def analyze_document(document_id: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Re-run extraction for an already-uploaded document."""
    doc = documents_repo.get(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    plan_type = doc.plan_type
    path = doc.source_path
    if not plan_type or not path or not os.path.exists(path):
        raise HTTPException(status_code=409, detail="Document has no source file to re-analyze")
    documents_repo.update_status(db, document_id, status="Processing", status_tone="blue", processing=True)
    background.add_task(_run_extraction, document_id, path, plan_type)
    return documents_repo.get(db, document_id).to_dict()


def _run_extraction(document_id: str, path: str, plan_type: str) -> None:
    """Background worker: extract BOMs and update the document record.

    Runs after the response is sent, so it opens its own DB session rather than
    reusing the request-scoped one.
    """
    result = extraction.extract_document(path, plan_type)
    with SessionLocal() as db:
        if documents_repo.get(db, document_id) is None:
            return
        documents_repo.set_line_items(db, document_id, result.groups)
        if result.error:
            documents_repo.update_status(
                db, document_id,
                status="Failed", status_tone="danger", processing=False,
                items="—", error=result.error,
            )
        else:
            documents_repo.update_status(
                db, document_id,
                status="Analyzed", status_tone="success", processing=False,
                items=str(result.total_items), summary=result.summary, mocked=result.mocked,
            )
