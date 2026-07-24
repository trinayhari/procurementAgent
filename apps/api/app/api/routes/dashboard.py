from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories import reference as reference_repo
from app.schemas.dashboard import Dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=Dashboard)
def get_dashboard(db: Session = Depends(get_db)):
    return reference_repo.get_dashboard(db)
