"""Document upload, AI extraction, and BOM retrieval.

Upload flow:
  1. POST a file (+ plan_type) → it's saved to the upload dir and a document
     record is created in 'Processing'.
  2. A FastAPI BackgroundTask runs GPT-4.1 vision extraction (see
     app.services.extraction) and writes the resulting BOM groups + status.
  3. The frontend polls GET /api/documents/{id} until it leaves 'Processing',
     then loads GET /api/documents/{id}/line-items.
"""
import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.config import settings
from app.repositories import seed
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
def get_document(document_id: str):
    doc = seed.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/line-items", response_model=List[LineItemGroup])
def get_document_line_items(document_id: str):
    """BOM groups extracted from one document."""
    if seed.get_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    groups = seed.get_document_line_items(document_id)
    return groups or []


@router.put("/{document_id}/line-items", response_model=List[LineItemGroup])
def save_document_line_items(document_id: str, payload: LineItemsUpdate):
    """Human-in-the-loop: replace a document's BOM with the reviewer's edits.

    Recomputes group counts and the document's item total, and flags it as edited.
    """
    if seed.get_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    groups = [g.model_dump() for g in payload.groups]
    return seed.save_document_line_items(document_id, groups)


@router.post("/{document_id}/confirm", response_model=Document)
def confirm_document(document_id: str):
    """Human-in-the-loop: mark a document's BOM as reviewed and approved."""
    doc = seed.confirm_document(document_id, datetime.now().strftime("%b %d, %Y"))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("", response_model=Document, status_code=201)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    plan_type: str = Form(default=None),
):
    """Upload a plan set and kick off background AI extraction."""
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

    doc = seed.add_document(
        name=os.path.splitext(safe_name)[0],
        doc_type=spec.label,
        pages=pages,
        plan_type=plan_type,
        date=datetime.now().strftime("%b %d, %Y"),
    )
    doc["sourcePath"] = dest  # retained in the store; stripped from the Document response
    background.add_task(_run_extraction, doc["id"], dest, plan_type)
    return doc


@router.post("/{document_id}/analyze", response_model=Document)
def analyze_document(document_id: str, background: BackgroundTasks):
    """Re-run extraction for an already-uploaded document."""
    doc = seed.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    plan_type = doc.get("planType")
    path = doc.get("sourcePath")
    if not plan_type or not path or not os.path.exists(path):
        raise HTTPException(status_code=409, detail="Document has no source file to re-analyze")
    doc.update(status="Processing", statusTone="blue", processing=True)
    background.add_task(_run_extraction, document_id, path, plan_type)
    return doc


def _run_extraction(document_id: str, path: str, plan_type: str) -> None:
    """Background worker: extract BOMs and update the document record in place."""
    doc = seed.get_document(document_id)
    if doc is None:
        return
    result = extraction.extract_document(path, plan_type)
    seed.set_document_line_items(document_id, result.groups)
    if result.error:
        doc.update(status="Failed", statusTone="danger", processing=False,
                   items="—", error=result.error)
    else:
        doc.update(
            status="Analyzed", statusTone="success", processing=False,
            items=str(result.total_items), summary=result.summary, mocked=result.mocked,
        )
