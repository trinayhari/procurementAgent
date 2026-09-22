"""Attach an already-stored file to a project as a document.

This is the part of `POST /api/documents` that runs after the upload has
been validated and persisted: plan-type checks, singleton slot replacement,
the document row, audit + activity logging, and the extraction kick-off.
It lives here so the upload route and the conversational intake (email,
Slack) share one code path instead of two drifting copies.

Callers hand over a storage locator (see services/storage.py), never a
request: the route streams its upload to storage first, the intake flow
receives attachments the webhook already stored.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import documents as documents_repo
from app.repositories import events as events_repo
from app.services import extraction, storage
from app.services.extraction import pdf

logger = logging.getLogger("procureai.documents_intake")

# File types a document may carry (plan sets, schedules, material lists).
ALLOWED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp"}

# Types the extractor can read; anything else only ever lands in an
# "additional document" slot, where nothing is extracted.
EXTRACTABLE_EXTENSIONS = pdf.PDF_EXTS | pdf.IMAGE_EXTS


class AttachError(ValueError):
    """The file cannot be attached as asked (bad plan type, unreadable PDF,
    a BOM slot given a spreadsheet). The route maps these to 400s."""


def _count_pages(locator: str, ext: str) -> int:
    """Page count for a stored file: 1 for an image, N for a PDF, 0 for
    anything the extractor cannot open. A .pdf that will not open is
    corrupt, which the caller must hear about."""
    with storage.local_copy(locator) as path:
        try:
            return pdf.page_count(path)
        except pdf.UnsupportedDocument as exc:
            if ext in pdf.PDF_EXTS:
                raise AttachError(
                    "Could not read this PDF: the file appears to be corrupt or incomplete"
                ) from exc
            return 0


def _sha256(locator: str) -> str:
    digest = hashlib.sha256()
    with storage.local_copy(locator) as path:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _run_in_thread(fn: Callable, *args) -> None:
    """Default scheduler: a daemon thread, so a caller with no request
    lifecycle (a webhook's background task, a Slack event) still gets its
    extraction run."""
    threading.Thread(target=fn, args=args, daemon=True, name="procureai-extract").start()


def attach_stored_file(
    db: Session,
    org_id: str,
    project_id: str,
    *,
    locator: str,
    filename: str,
    plan_type: str,
    actor: Optional[User],
    pages: Optional[int] = None,
    sha256: Optional[str] = None,
    size: Optional[int] = None,
    schedule: Optional[Callable[..., None]] = None,
) -> Document:
    """Register a stored file as a document on `project_id` and start extraction.

    `locator` must already live in the active storage backend. `pages`,
    `sha256` and `size` are accepted from a caller that computed them while
    validating (the upload route hashes as it streams); when omitted they are
    read from storage here. `schedule(fn, *args)` runs the extraction pipeline;
    the route passes `BackgroundTasks.add_task`, everyone else gets a daemon
    thread. Raises AttachError when the plan type does not fit the file.
    """
    spec = extraction.registry.get(plan_type)
    if spec is None or not spec.enabled:
        raise AttachError(f"Unsupported or disabled plan type '{plan_type}'")

    safe_name = os.path.basename(filename or "document")
    ext = os.path.splitext(safe_name)[1].lower()
    if pages is None:
        pages = _count_pages(locator, ext)
    # A BOM plan slot only makes sense for something the extractor can read
    # (PDF / image). Spreadsheets belong in the additional-documents slot.
    if spec.categories and pages == 0:
        raise AttachError(
            f"{spec.label} uploads must be a PDF or image: "
            f"file '{ext or safe_name}' as an additional document instead"
        )
    if sha256 is None:
        sha256 = _sha256(locator)
    if size is None:
        size = storage.size(locator) or 0

    # Single-document slots (site / building / electrical plan) hold one
    # document each: re-uploading that plan type replaces the prior one.
    if spec.singleton:
        documents_repo.delete_for_plan_type(db, org_id, project_id, plan_type)

    # "Additional Document" slots have no BOM categories, so there is no BOM
    # to extract, but every renderable document still goes through TIMELINE
    # extraction (schedules/contracts usually arrive as additional documents).
    extractable = bool(spec.categories)
    analyzable = extractable or pages > 0

    doc = documents_repo.add(
        db,
        org_id=org_id,
        name=os.path.splitext(safe_name)[0],
        doc_type=spec.label,
        pages=pages,
        plan_type=plan_type,
        date=datetime.now().strftime("%b %d, %Y"),
        project_id=project_id,
        source_path=locator,
        has_file=True,
        status="Processing" if analyzable else "Analyzed",
        status_tone="blue" if analyzable else "success",
        checksum_sha256=sha256,
    )
    audit_repo.log(
        db, org_id, actor, "document.uploaded", "document", doc.id,
        project_id=project_id,
        detail={
            "name": doc.name, "planType": plan_type, "pages": pages,
            "bytes": size, "sha256": sha256,
            "storage": storage.backend_name(),
        },
    )
    events_repo.log(
        db,
        org_id,
        project_id,
        title=f"{'Plans' if extractable else 'Document'} uploaded: {doc.name}",
        icon="file",
        tone="blue",
        meta=spec.label + (f" · {pages} page{'s' if pages != 1 else ''}" if pages else ""),
    )
    if analyzable:
        # Resolved at call time, not import time: the route module imports
        # this one, and tests stub `documents._run_pipeline` on the route.
        from app.api.routes import documents as documents_routes

        run = schedule or _run_in_thread
        run(documents_routes._run_pipeline, org_id, doc.id, locator, plan_type)
    return doc
