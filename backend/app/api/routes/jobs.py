"""Background-job visibility + retry — the operator-facing exception queue.

GET /api/jobs?status=error lists failed jobs (search/ingest runs that crashed
or were interrupted by a restart); POST /api/jobs/{id}/retry re-runs one from
its recorded parameters.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.routes import sourcing
from app.db import get_db
from app.repositories import jobs as jobs_repo

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(status: str = "", limit: int = 100, db: Session = Depends(get_db)):
    return jobs_repo.list_jobs(db, status=status or None, limit=min(max(limit, 1), 500))


@router.post("/{job_id}/retry")
def retry_job(job_id: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    job = jobs_repo.get(db, job_id)
    if job is None:
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
        jobs_repo.retrying(db, job_id)
        background.add_task(
            sourcing.run_search_job,
            job_id,
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
        jobs_repo.retrying(db, job_id)
        background.add_task(sourcing.run_ingest_job, job_id, detail["projectId"])
    else:
        raise HTTPException(status_code=400, detail=f"Unknown job kind '{job['kind']}'")
    return jobs_repo.get(db, job_id)
