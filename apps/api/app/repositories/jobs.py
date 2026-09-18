"""Database accessors for background jobs (the durable job/status store).

Jobs carry the parameters of a search/ingest run (project id, location, package),
so they are tenant data: the exception queue and every poller filter on `org_id`.
"""
import json
import time
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.background_job import BackgroundJob


def _new_id() -> str:
    """Time-prefixed id: lexicographic order == creation order, so 'latest'
    lookups are unambiguous even for jobs created within the same second
    (created_at has second granularity)."""
    return f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}"


def _get_row(db: Session, org_id: str, job_id: str) -> Optional[BackgroundJob]:
    """The ORM row, or None when it doesn't exist *or* belongs to another org."""
    row = db.get(BackgroundJob, job_id)
    return row if row is not None and row.organization_id == org_id else None


def start(
    db: Session, org_id: str, kind: str, ref: str, detail: Optional[dict] = None
) -> dict:
    """Record a job as running and return it (the worker keeps its id)."""
    row = BackgroundJob(
        organization_id=org_id,
        id=_new_id(),
        kind=kind,
        ref=ref,
        status="running",
        detail=json.dumps(detail or {}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


def get(db: Session, org_id: str, job_id: str) -> Optional[dict]:
    row = _get_row(db, org_id, job_id)
    return row.to_dict() if row else None


def _update(
    db: Session,
    org_id: str,
    job_id: str,
    status: str,
    error: Optional[str] = None,
    detail_updates: Optional[dict] = None,
) -> Optional[dict]:
    row = _get_row(db, org_id, job_id)
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


def finish(
    db: Session, org_id: str, job_id: str, detail_updates: Optional[dict] = None
) -> Optional[dict]:
    return _update(db, org_id, job_id, status="done", detail_updates=detail_updates)


def fail(
    db: Session,
    org_id: str,
    job_id: str,
    error: str,
    detail_updates: Optional[dict] = None,
) -> Optional[dict]:
    return _update(
        db, org_id, job_id, status="error", error=error, detail_updates=detail_updates
    )


def retrying(db: Session, org_id: str, job_id: str) -> Optional[dict]:
    """Flip a failed job back to running for another attempt."""
    row = _get_row(db, org_id, job_id)
    if row is None:
        return None
    row.status = "running"
    row.error = None
    row.attempts += 1
    db.commit()
    db.refresh(row)
    return row.to_dict()


def latest(db: Session, org_id: str, kind: str, ref: str) -> Optional[dict]:
    """The most recent job for (kind, ref) — what pollers report on."""
    row = db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.organization_id == org_id,
            BackgroundJob.kind == kind,
            BackgroundJob.ref == ref,
        )
        .order_by(BackgroundJob.id.desc())  # ids are time-ordered (see _new_id)
        .limit(1)
    ).first()
    return row.to_dict() if row else None


def list_jobs(
    db: Session, org_id: str, status: Optional[str] = None, limit: int = 100
) -> List[dict]:
    stmt = select(BackgroundJob).where(BackgroundJob.organization_id == org_id)
    if status:
        stmt = stmt.where(BackgroundJob.status == status)
    stmt = stmt.order_by(BackgroundJob.id.desc()).limit(limit)
    return [r.to_dict() for r in db.scalars(stmt).all()]


def fail_orphaned_running(db: Session) -> List[str]:
    """Mark jobs stuck in 'running' as failed (called on startup).

    Jobs run as in-process background tasks; if the process dies mid-run the
    row is pinned in 'running' forever. At boot nothing can still be running,
    so flip those to error — they surface in the exception queue for retry.

    Deliberately cross-organization: this is boot-time maintenance rather than a
    request, so there is no caller whose org could scope it.
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
