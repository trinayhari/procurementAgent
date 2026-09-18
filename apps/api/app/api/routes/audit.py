"""Read-only audit-log endpoint (append-only trail; no mutation routes exist)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.user import User
from app.repositories import audit as audit_repo

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit_events(
    project_id: str = "",
    action: str = "",
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The caller's organization's audit trail.

    `project_id` narrows within the org; it can't widen past it, so passing
    another tenant's project id returns an empty list rather than their events.
    """
    return audit_repo.list_events(
        db,
        current_user.organization_id,
        project_id=project_id or None,
        action=action or None,
        limit=min(max(limit, 1), 1000),
    )
