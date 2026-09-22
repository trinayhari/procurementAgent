"""Intake from the dashboard: run a request by hand, list what arrived.

POST /api/intake/test runs the same service the email and Slack transports
use, with documents the caller already uploaded standing in for attachments.
It exists so the flow can be exercised without a mailbox (manual testing,
the dashboard's "send to the agent" box). GET /api/projects/{id}/intake
lists the intake emails filed on a project.
"""
import json
import os
import shutil
import tempfile
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.inbound_email import InboundEmail
from app.models.user import User
from app.repositories import documents as documents_repo
from app.repositories import projects as projects_repo
from app.services import storage
from app.services.inbound import intake as intake_service

router = APIRouter(tags=["intake"])


class IntakeTestRequest(BaseModel):
    subject: str = ""
    text: str = ""
    # Ids of documents already uploaded; their files are copied so the
    # originals stay attached to wherever they were uploaded.
    attachments: List[str] = Field(default_factory=list)


class IntakeDocument(BaseModel):
    id: str
    name: str
    planType: str


class IntakeTestResult(BaseModel):
    projectId: str
    projectCreated: bool
    documents: List[IntakeDocument]
    needBy: Optional[str] = None
    summary: str


class IntakeRow(BaseModel):
    id: str
    subject: str
    fromEmail: str
    fromName: str
    receivedAt: str
    processedAt: Optional[str] = None
    attachments: int
    summary: str
    error: Optional[str] = None


def _duplicate_stored(locator: str, filename: str) -> storage.StoredFile:
    """Copy a stored file under a new locator (local or S3), so two document
    rows never share one file: deleting either would take the other's."""
    suffix = os.path.splitext(filename)[1].lower()
    fd, tmp_path = tempfile.mkstemp(prefix="procureai-intake-", suffix=suffix)
    os.close(fd)
    with storage.local_copy(locator) as path:
        shutil.copyfile(path, tmp_path)
    size = os.path.getsize(tmp_path)
    return storage.persist_temp(storage.StoredFile(locator=tmp_path, sha256="", size=size), filename)


@router.post("/api/intake/test", response_model=IntakeTestResult)
def run_intake_test(
    payload: IntakeTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    attachments = []
    for doc_id in payload.attachments:
        doc = documents_repo.get(db, org_id, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")
        if not storage.exists(doc.source_path):
            raise HTTPException(status_code=410, detail=f"Document '{doc_id}' has no stored file")
        ext = os.path.splitext(doc.source_path)[1].lower()
        filename = f"{doc.name}{ext}" if doc.name else os.path.basename(doc.source_path)
        stored = _duplicate_stored(doc.source_path, filename)
        attachments.append({
            "filename": filename,
            "mimeType": "application/pdf" if ext == ".pdf" else "application/octet-stream",
            "size": stored.size,
            "locator": stored.locator,
        })
    result = intake_service.handle_request(
        db,
        org_id=org_id,
        user=current_user,
        text=payload.text,
        subject=payload.subject,
        attachments=attachments,
        thread=None,
    )
    return {
        "projectId": result.project_id,
        "projectCreated": result.project_created,
        "documents": result.documents,
        "needBy": result.need_by,
        "summary": result.summary,
    }


def _summarise(row: InboundEmail) -> str:
    """One line for the list: the files, else the start of the message."""
    try:
        files = [a.get("filename", "") for a in json.loads(row.attachments or "[]") if isinstance(a, dict)]
    except ValueError:
        files = []
    files = [f for f in files if f]
    if files:
        return f"{len(files)} file{'s' if len(files) != 1 else ''}: " + ", ".join(files[:5])
    text = " ".join((row.text or "").split())
    return text[:160] or "(no text)"


@router.get("/api/projects/{project_id}/intake", response_model=List[IntakeRow])
def list_project_intake(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    if projects_repo.get_project(db, org_id, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = db.scalars(
        select(InboundEmail)
        .where(
            InboundEmail.organization_id == org_id,
            InboundEmail.project_id == project_id,
            InboundEmail.kind == "intake",
        )
        .order_by(InboundEmail.received_at.desc())
    ).all()
    out = []
    for row in rows:
        try:
            n_files = len(json.loads(row.attachments or "[]"))
        except ValueError:
            n_files = 0
        out.append({
            "id": row.id,
            "subject": row.subject,
            "fromEmail": row.from_email,
            "fromName": row.from_name,
            "receivedAt": row.received_at.isoformat() if row.received_at else "",
            "processedAt": row.processed_at.isoformat() if row.processed_at else None,
            "attachments": n_files,
            "summary": _summarise(row),
            "error": row.error,
        })
    return out
