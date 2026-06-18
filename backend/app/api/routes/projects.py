from typing import List

from fastapi import APIRouter, HTTPException

from app.repositories import seed
from app.schemas.document import Document, LineItemGroup
from app.schemas.project import Project, ProjectCreate, ProjectDetail
from app.schemas.quote import Comparison, Quote
from app.schemas.rfq import Rfq, RfqFolder
from app.schemas.supplier import Supplier
from app.schemas.timeline import Timeline

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=List[Project])
def list_projects():
    return seed.PROJECTS


@router.post("", response_model=Project, status_code=201)
def create_project(payload: ProjectCreate):
    return seed.create_project(
        name=payload.name,
        loc=payload.loc,
        value=payload.value,
        stage=payload.stage.value,
    )


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str):
    project = seed.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {**project, "overviewCards": seed.OVERVIEW_CARDS, "packages": seed.PACKAGES}


@router.get("/{project_id}/documents", response_model=List[Document])
def list_documents(project_id: str):
    _require_project(project_id)
    return seed.DOCUMENTS


@router.get("/{project_id}/line-items", response_model=List[LineItemGroup])
def list_line_items(project_id: str):
    _require_project(project_id)
    return seed.LINE_ITEMS


@router.get("/{project_id}/suppliers", response_model=List[Supplier])
def list_project_suppliers(project_id: str):
    _require_project(project_id)
    return seed.SUPPLIERS


@router.get("/{project_id}/quotes", response_model=List[Quote])
def list_quotes(project_id: str):
    _require_project(project_id)
    return seed.QUOTES


@router.get("/{project_id}/rfqs", response_model=List[Rfq])
def list_rfqs(project_id: str):
    _require_project(project_id)
    return seed.RFQS


@router.get("/{project_id}/rfq-folders", response_model=List[RfqFolder])
def list_rfq_folders(project_id: str):
    _require_project(project_id)
    return seed.RFQ_FOLDERS


@router.get("/{project_id}/timeline", response_model=Timeline)
def get_timeline(project_id: str):
    _require_project(project_id)
    return {"milestones": seed.MILESTONES, "gantt": seed.GANTT, "ganttCols": seed.GANTT_COLS}


@router.get("/{project_id}/packages/{pkg}/comparison", response_model=Comparison)
def get_comparison(project_id: str, pkg: str):
    _require_project(project_id)
    comparison = seed.COMPARISONS.get(pkg)
    if comparison is None:
        raise HTTPException(status_code=404, detail="No comparison for package")
    return comparison


def _require_project(project_id: str) -> dict:
    project = seed.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
