"""Database-backed accessors for documents (uploaded plan sets + seed demo docs).

Documents are persisted to SQLite via SQLAlchemy so uploads, their project
association, and their extracted BOMs survive a backend restart. The shared
``seed.DOCUMENTS`` / ``seed.LINE_ITEMS`` literals are only used to populate the
prototype's Riverside demo docs once, on first run.
"""
import json
import os
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.repositories import seed

# Plan type for a hand-built "custom BOM" — a bill of materials the user types by
# hand in the Documents panel (no file, no extraction). Kept here so the routes
# that create, list, and source from these documents agree on one key.
CUSTOM_BOM_PLAN_TYPE = "custom_bom"


def list_custom_boms(db: Session, project_id: str) -> List[Document]:
    """The project's hand-built custom BOMs, newest first."""
    return list(
        db.scalars(
            select(Document)
            .where(
                Document.project_id == project_id,
                Document.plan_type == CUSTOM_BOM_PLAN_TYPE,
            )
            .order_by(Document.seq.desc())
        ).all()
    )


def is_custom_bom(db: Session, project_id: str, doc_id: str) -> bool:
    """True when `doc_id` is a custom BOM belonging to `project_id`."""
    doc = db.get(Document, doc_id)
    return (
        doc is not None
        and doc.project_id == project_id
        and doc.plan_type == CUSTOM_BOM_PLAN_TYPE
    )


def _next_seq(db: Session) -> int:
    return (db.scalar(select(func.max(Document.seq))) or 0) + 1


def list_for_project(db: Session, project_id: str) -> List[dict]:
    """Documents belonging to one project, newest upload first."""
    rows = db.scalars(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.seq.desc())
    ).all()
    return [d.to_dict() for d in rows]


def get(db: Session, doc_id: str) -> Optional[Document]:
    return db.get(Document, doc_id)


def add(
    db: Session,
    *,
    name: str,
    doc_type: str,
    pages: int,
    plan_type: Optional[str],
    date: str,
    project_id: str,
    source_path: Optional[str] = None,
    has_file: bool = False,
    status: str = "Processing",
    status_tone: str = "blue",
) -> Document:
    """Register an uploaded document and return the persisted row."""
    seq = _next_seq(db)
    doc = Document(
        seq=seq,
        id=f"upload-{seq}",
        project_id=project_id,
        name=name,
        type=doc_type,
        date=date,
        status=status,
        status_tone=status_tone,
        items="—",
        pages=pages,
        processing=status == "Processing",
        has_file=has_file,
        source_path=source_path,
        plan_type=plan_type,
        reviewed=False,
        edited=False,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def delete(db: Session, doc_id: str) -> Optional[Document]:
    """Delete a document and best-effort unlink its on-disk source file.

    Returns the deleted row, or None if no such document exists.
    """
    doc = db.get(Document, doc_id)
    if doc is None:
        return None
    path = doc.source_path
    db.delete(doc)
    db.commit()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass  # the record is already gone; leave the orphaned file
    return doc


def delete_for_plan_type(db: Session, project_id: str, plan_type: str) -> List[str]:
    """Delete any documents of one plan type in a project (and their files).

    Used to keep the single-document plan slots (site / building / electrical)
    to one document each: re-uploading that plan type replaces the prior one.
    Returns the ids that were removed.
    """
    rows = db.scalars(
        select(Document).where(
            Document.project_id == project_id, Document.plan_type == plan_type
        )
    ).all()
    removed = []
    for doc in rows:
        path = doc.source_path
        removed.append(doc.id)
        db.delete(doc)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    if removed:
        db.commit()
    return removed


def set_line_items(db: Session, doc_id: str, groups: List[dict]) -> None:
    """Store AI-extracted BOM groups (overwrites any existing)."""
    doc = db.get(Document, doc_id)
    if doc is None:
        return
    doc.line_items = json.dumps(groups)
    db.commit()


def save_line_items(db: Session, doc_id: str, groups: List[dict]) -> List[dict]:
    """Persist a human-edited BOM: recompute counts/total, flag the doc edited."""
    clean = [{**g, "count": len(g.get("items", []))} for g in groups]
    doc = db.get(Document, doc_id)
    if doc is not None:
        doc.line_items = json.dumps(clean)
        doc.items = str(sum(g["count"] for g in clean))
        doc.edited = True
        db.commit()
    return clean


def get_line_items(db: Session, doc_id: str) -> Optional[List[dict]]:
    """Per-document BOM groups: a doc's own extracted/edited items take
    precedence; seed demo docs (no plan type, no own items) fall back to the
    shared line-item groups so the prototype still renders."""
    from app.repositories import reference as reference_repo

    doc = db.get(Document, doc_id)
    if doc is None:
        return None
    own = doc.get_line_items()
    if own is not None:
        return own
    if not doc.plan_type:  # a seed/demo doc, not an upload
        return reference_repo.list_line_item_groups(db)
    return None


def confirm(db: Session, doc_id: str, when: str) -> Optional[Document]:
    """Mark a document's BOM as human-reviewed/approved.

    A hand-built custom BOM has no upload/extraction status of its own, so once
    the user confirms it we surface it as "Saved" rather than the initial
    "Draft". It stays editable — confirming doesn't lock it.
    """
    doc = db.get(Document, doc_id)
    if doc is not None:
        doc.reviewed = True
        doc.reviewed_at = when
        if doc.plan_type == CUSTOM_BOM_PLAN_TYPE:
            doc.status = "Saved"
            doc.status_tone = "success"
        db.commit()
        db.refresh(doc)
    return doc


def update_status(db: Session, doc_id: str, **fields) -> Optional[Document]:
    """Patch arbitrary columns on a document (used by the extraction worker)."""
    doc = db.get(Document, doc_id)
    if doc is None:
        return None
    for key, value in fields.items():
        setattr(doc, key, value)
    db.commit()
    db.refresh(doc)
    return doc


def fail_orphaned_processing(db: Session) -> List[str]:
    """Mark documents stuck in 'Processing' as failed (called on startup).

    Extraction runs in a background task in the API process. If that process is
    killed mid-extraction (e.g. an OOM SIGKILL while rasterising a large plan
    set), the task dies without ever writing a terminal status, so the document
    is pinned in 'Processing' forever — and the frontend polls it indefinitely.
    On boot, no extraction can still be in flight, so any such row is orphaned:
    flip it to 'Failed' so the user sees a clear outcome and can re-run.

    Returns the ids that were reset.
    """
    rows = db.scalars(select(Document).where(Document.processing.is_(True))).all()
    ids = []
    for doc in rows:
        doc.status = "Failed"
        doc.status_tone = "danger"
        doc.processing = False
        doc.items = "—"
        doc.error = "Extraction was interrupted by a server restart — please re-run."
        ids.append(doc.id)
    if ids:
        db.commit()
    return ids


def seed_starter_documents(db: Session) -> None:
    """Populate the prototype's Riverside demo docs once, on an empty table."""
    if db.scalar(select(func.count()).select_from(Document)):
        return
    # Insert reversed so the first seed doc gets the highest seq and sorts to the
    # top under ORDER BY seq DESC (mirrors the old in-memory list order).
    for i, d in enumerate(reversed(seed.DOCUMENTS), start=1):
        db.add(
            Document(
                seq=i,
                id=d["id"],
                project_id=d.get("projectId", "riverside"),
                name=d["name"],
                type=d["type"],
                date=d["date"],
                status=d["status"],
                status_tone=d["statusTone"],
                items=d.get("items", "—"),
                pages=d.get("pages", 0),
                processing=d.get("processing", False),
                has_file=False,
                plan_type=None,
            )
        )
    db.commit()


def rehydrate_uploads(db: Session, upload_dir: str, project_id: str = "riverside") -> int:
    """Re-register upload-dir files that aren't tracked by any document row.

    With documents now persisted, this only matters for files dropped into the
    upload dir out-of-band (e.g. copied in manually) — those are attached to
    `project_id` so they stay previewable. Returns the number added.
    """
    if not os.path.isdir(upload_dir):
        return 0
    tracked = {
        os.path.basename(p)
        for p in db.scalars(select(Document.source_path)).all()
        if p
    }
    from datetime import datetime

    seq = _next_seq(db)
    added = 0
    for fname in sorted(os.listdir(upload_dir)):
        path = os.path.join(upload_dir, fname)
        if fname.startswith(".") or not os.path.isfile(path) or fname in tracked:
            continue
        db.add(
            Document(
                seq=seq,
                id=f"upload-{seq}",
                project_id=project_id,
                name=os.path.splitext(fname)[0],
                type="Uploaded",
                date=datetime.fromtimestamp(os.path.getmtime(path)).strftime("%b %d, %Y"),
                status="Analyzed",
                status_tone="success",
                items="—",
                pages=0,
                processing=False,
                has_file=True,
                source_path=path,
                plan_type=None,
            )
        )
        seq += 1
        added += 1
    if added:
        db.commit()
    return added
