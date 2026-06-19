from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories import documents as documents_repo
from app.repositories import projects as projects_repo
from app.repositories import quotes as quotes_repo
from app.repositories import seed
from app.services.quotes import comparison as comparison_service
from app.services.sourcing import packages
from app.schemas.document import Document, LineItemGroup
from app.schemas.project import Project, ProjectCreate, ProjectDetail
from app.schemas.quote import Comparison, Quote
from app.schemas.rfq import Rfq, RfqFolder
from app.schemas.supplier import Supplier
from app.schemas.timeline import Timeline

router = APIRouter(prefix="/api/projects", tags=["projects"])


# Projects are persisted (SQLite via SQLAlchemy). The per-project sub-resources
# below still serve prototype seed data; they only use the project to 404 on
# unknown ids.
@router.get("", response_model=List[Project])
def list_projects(db: Session = Depends(get_db)):
    return projects_repo.list_projects(db)


@router.post("", response_model=Project, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    return projects_repo.create_project(
        db,
        name=payload.name,
        loc=payload.loc,
        value=payload.value,
        stage=payload.stage.value,
    )


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = _require_project(project_id, db)
    return {**project, "overviewCards": seed.OVERVIEW_CARDS, "packages": seed.PACKAGES}


@router.get("/{project_id}/documents", response_model=List[Document])
def list_documents(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return documents_repo.list_for_project(db, project_id)


@router.get("/{project_id}/line-items", response_model=List[LineItemGroup])
def list_line_items(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return seed.LINE_ITEMS


@router.get("/{project_id}/suppliers", response_model=List[Supplier])
def list_project_suppliers(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return seed.SUPPLIERS


@router.get("/{project_id}/quotes", response_model=List[Quote])
def list_quotes(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    # Prefer real ingested quotes; fall back to the prototype seed when none exist
    # (keeps the Riverside demo populated before any quotes are ingested).
    rows = quotes_repo.list_quote_rows(db, project_id)
    return rows if rows else seed.QUOTES


@router.get("/{project_id}/rfqs", response_model=List[Rfq])
def list_rfqs(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return seed.RFQS


@router.get("/{project_id}/rfq-folders", response_model=List[RfqFolder])
def list_rfq_folders(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return seed.RFQ_FOLDERS


@router.get("/{project_id}/timeline", response_model=Timeline)
def get_timeline(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return {"milestones": seed.MILESTONES, "gantt": seed.GANTT, "ganttCols": seed.GANTT_COLS}


@router.get("/{project_id}/packages/{pkg}/comparison", response_model=Comparison)
def get_comparison(project_id: str, pkg: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    # `pkg` may arrive as a package key ("water") or a display label
    # ("Water Utilities"); resolve to the canonical key for the quote lookup.
    key = pkg if packages.is_valid(pkg) else packages.category_for_label(pkg)
    label = packages.label_for(key) if key else pkg
    if key:
        dynamic = comparison_service.build_comparison(db, project_id, key, label)
        if dynamic is not None:
            return dynamic
    # No ingested quotes yet → prototype seed comparison (keyed by label).
    comparison = seed.COMPARISONS.get(pkg) or (seed.COMPARISONS.get(label) if key else None)
    if comparison is None:
        raise HTTPException(status_code=404, detail="No comparison for package")
    return comparison


def _require_project(project_id: str, db: Session) -> dict:
    project = projects_repo.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
