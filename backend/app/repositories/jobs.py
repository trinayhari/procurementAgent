"""Database accessors for background jobs (the durable job/status store)."""
import json
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.background_job import BackgroundJob


def start(db: Session, kind: str, ref: str, detail: Optional[dict] = None) -> dict:
    """Record a job as running and return it (the worker keeps its id)."""
    row = BackgroundJob(
        id=uuid.uuid4().hex,
        kind=kind,
        ref=ref,
        status="running",
        detail=json.dumps(detail or {}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


def get(db: Session, job_id: str) -> Optional[dict]:
    row = db.get(BackgroundJob, job_id)
    return row.to_dict() if row else None


def _update(
    db: Session,
    job_id: str,
    status: str,
    error: Optional[str] = None,
    detail_updates: Optional[dict] = None,
) -> Optional[dict]:
    row = db.get(BackgroundJob, job_id)
    if row is None:
        return None
    row.status = status
    row.error = error
    if detail_updates:
        detail = json.loads(row.detail or "{}")
        detail.update(detail_updates)
        row.detail = json.dumps(detail)
    db.commit()
    db.refresh(row)
    return row.to_dict()


def finish(db: Session, job_id: str, detail_updates: Optional[dict] = None) -> Optional[dict]:
    return _update(db, job_id, status="done", detail_updates=detail_updates)


def fail(db: Session, job_id: str, error: str, detail_updates: Optional[dict] = None) -> Optional[dict]:
    return _update(db, job_id, status="error", error=error, detail_updates=detail_updates)


def retrying(db: Session, job_id: str) -> Optional[dict]:
    """Flip a failed job back to running for another attempt."""
    row = db.get(BackgroundJob, job_id)
    if row is None:
        return None
    row.status = "running"
    row.error = None
    row.attempts += 1
    db.commit()
    db.refresh(row)
    return row.to_dict()


def latest(db: Session, kind: str, ref: str) -> Optional[dict]:
    """The most recent job for (kind, ref) — what pollers report on."""
    row = db.scalars(
        select(BackgroundJob)
        .where(BackgroundJob.kind == kind, BackgroundJob.ref == ref)
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    ).first()
    return row.to_dict() if row else None


def list_jobs(db: Session, status: Optional[str] = None, limit: int = 100) -> List[dict]:
    stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
    if status:
        stmt = select(BackgroundJob).where(BackgroundJob.status == status).order_by(
            BackgroundJob.created_at.desc()
        ).limit(limit)
    return [r.to_dict() for r in db.scalars(stmt).all()]


def fail_orphaned_running(db: Session) -> List[str]:
    """Mark jobs stuck in 'running' as failed (called on startup).

    Jobs run as in-process background tasks; if the process dies mid-run the
    row is pinned in 'running' forever. At boot nothing can still be running,
    so flip those to error — they surface in the exception queue for retry.
    """
    rows = db.scalars(select(BackgroundJob).where(BackgroundJob.status == "running")).all()
    ids = []
    for row in rows:
        row.status = "error"
        row.error = "Interrupted by a server restart — retry from the exception queue."
        ids.append(row.id)
    if ids:
        db.commit()
    return ids
