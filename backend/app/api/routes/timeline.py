"""Timeline event endpoints (cross-document, project-scoped data).

The assembled per-project schedule is served from
GET /api/projects/{project_id}/timeline; this router carries the endpoints that
act on the underlying extracted events themselves.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import timeline as timeline_repo
from app.schemas.timeline import MilestoneDoneResult, MilestoneDoneUpdate

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


@router.post("/events/{event_id}/done", response_model=MilestoneDoneResult)
def set_event_done(
    event_id: int,
    payload: MilestoneDoneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Human check-off for a milestone: the schedule can't know a milestone
    actually happened from dates alone, so completion is confirmed (or undone)
    by the user. Applies to every same-named event in the project, and survives
    document re-analysis."""
    result = timeline_repo.set_done(
        db, event_id, payload.done, when=datetime.now().strftime("%b %d, %Y")
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Timeline event not found")
    audit_repo.log(
        db, current_user, "milestone.checked" if payload.done else "milestone.unchecked",
        "timeline_event", str(event_id), detail={"updated": result["updated"]},
    )
    return {"updated": result["updated"]}
