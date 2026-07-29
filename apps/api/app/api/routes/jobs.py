"""Background-job visibility + retry — the operator-facing exception queue.

GET /api/jobs?status=error lists failed jobs (search/ingest runs that crashed
or were interrupted by a restart); POST /api/jobs/{id}/retry re-runs one from
its recorded parameters. Both are scoped to the caller's organization: a job's
detail carries project ids and search parameters, and a retry would re-run work
inside whichever tenant owns it.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes import sourcing
from app.core.security import get_current_user
from app.db import get_db
from app.models.user import User
from app.repositories import jobs as jobs_repo

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    status: str = "",
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return jobs_repo.list_jobs(
        db,
        current_user.organization_id,
        status=status or None,
        limit=min(max(limit, 1), 500),
    )


@router.post("/{job_id}/retry")
def retry_job(
    job_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    job = jobs_repo.get(db, org_id, job_id)
    if job is None:
        # 404 covers both "no such job" and "another org's job".
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "error":
        raise HTTPException(
            status_code=409, detail=f"Only failed jobs can be retried (status: {job['status']})"
        )
    detail = job.get("detail") or {}
    if job["kind"] == sourcing.SEARCH_JOB:
        required = {"projectId", "package", "loc"}
        if not required.issubset(detail):
            raise HTTPException(status_code=409, detail="Job is missing its original parameters")
        jobs_repo.retrying(db, org_id, job_id)
        background.add_task(
            sourcing.run_search_job,
            job_id,
            org_id,
            detail["projectId"],
            detail["loc"],
            detail["package"],
            detail.get("radiusMi", 75),
            detail.get("keywords"),
            detail.get("label"),
        )
    elif job["kind"] == sourcing.INGEST_JOB:
        if "projectId" not in detail:
            raise HTTPException(status_code=409, detail="Job is missing its original parameters")
        jobs_repo.retrying(db, org_id, job_id)
        background.add_task(sourcing.run_ingest_job, job_id, org_id, detail["projectId"])
    else:
        raise HTTPException(status_code=400, detail=f"Unknown job kind '{job['kind']}'")
    return jobs_repo.get(db, org_id, job_id)
