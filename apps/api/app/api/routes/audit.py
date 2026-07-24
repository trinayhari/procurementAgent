"""Read-only audit-log endpoint (append-only trail; no mutation routes exist)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories import audit as audit_repo

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit_events(
    project_id: str = "",
    action: str = "",
    limit: int = 200,
    db: Session = Depends(get_db),
):
    return audit_repo.list_events(
        db,
        project_id=project_id or None,
        action=action or None,
        limit=min(max(limit, 1), 1000),
    )
