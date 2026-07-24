from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories import events as events_repo
from app.repositories import reference as reference_repo
from app.schemas.dashboard import Dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
def get_dashboard(db: Session = Depends(get_db)):
    data = reference_repo.get_dashboard(db)
    # Prefer the real, cross-project activity stream (events logged as users work
    # their projects) over the seeded `activity_items`, which is empty unless the
    # demo seed is enabled. Kept small so the dashboard panel is a glance.
    recent = events_repo.list_recent(db)
    if recent:
        data["activity"] = recent
    return data
