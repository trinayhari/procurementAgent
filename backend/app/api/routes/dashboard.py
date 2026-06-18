from fastapi import APIRouter

from app.repositories import seed
from app.schemas.dashboard import Dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
def get_dashboard():
    return {"metrics": seed.METRICS, "activity": seed.ACTIVITY}
