from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import DEMO_ORG_ID, get_db
from app.models.user import User
from app.repositories import events as events_repo
from app.repositories import reference as reference_repo
from app.schemas.dashboard import Dashboard
from app.services import metrics as metrics_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    # KPI tiles are computed from this organization's own projects, RFQs,
    # quotes and awards — the same arithmetic for the demo org and for a
    # brand-new tenant (see services/metrics.py for the definitions).
    metrics = metrics_service.dashboard_metrics(db, org_id)
    # Prefer the real, cross-project activity stream (events logged as users
    # work their projects). Only the demo organization falls back to the
    # prototype's seeded feed — it names the demo projects, never another
    # tenant's.
    activity = events_repo.list_recent(db, org_id)
    if not activity and org_id == DEMO_ORG_ID:
        activity = reference_repo.list_activity(db)
    return {"metrics": metrics, "activity": activity}
