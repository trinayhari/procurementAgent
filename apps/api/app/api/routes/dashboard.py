from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.user import User
from app.repositories import events as events_repo
from app.repositories import reference as reference_repo
from app.schemas.dashboard import Dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # `metrics` come from the global reference tables (seeded literals, the same
    # for every tenant); the activity feed is real customer data and is scoped
    # to the caller's organization.
    data = reference_repo.get_dashboard(db)
    # Prefer the real, cross-project activity stream (events logged as users work
    # their projects) over the seeded `activity_items`, which is empty unless the
    # demo seed is enabled. Kept small so the dashboard panel is a glance.
    recent = events_repo.list_recent(db, current_user.organization_id)
    if recent:
        data["activity"] = recent
    return data
