from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import DEMO_ORG_ID, get_db
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
    org_id = current_user.organization_id
    # The seeded metric literals and demo activity feed are the prototype's
    # Riverside story: only the demo organization gets them. Every other
    # tenant sees its own activity stream (and, until metrics are computed
    # from real data, no metric cards) — never another tenant's project
    # names on its dashboard.
    if org_id == DEMO_ORG_ID:
        data = reference_repo.get_dashboard(db)
    else:
        data = {"metrics": [], "activity": []}
    # Prefer the real, cross-project activity stream (events logged as users work
    # their projects) over the seeded `activity_items`. Kept small so the
    # dashboard panel is a glance.
    recent = events_repo.list_recent(db, org_id)
    if recent:
        data["activity"] = recent
    return data
