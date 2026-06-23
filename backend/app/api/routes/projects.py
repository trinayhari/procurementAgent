from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories import documents as documents_repo
from app.repositories import events as events_repo
from app.repositories import projects as projects_repo
from app.repositories import quotes as quotes_repo
from app.repositories import reference as reference_repo
from app.repositories import suppliers as suppliers_repo
from app.services.quotes import comparison as comparison_service
from app.services.quotes import line_comparison as line_comparison_service
from app.services.sourcing import packages
from app.schemas.document import Document, LineItemGroup
from app.schemas.project import Project, ProjectCreate, ProjectDetail
from app.schemas.quote import (
    AwardRequest,
    AwardResult,
    Comparison,
    LineComparison,
    Quote,
)
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
    project = projects_repo.create_project(
        db,
        name=payload.name,
        loc=payload.loc,
        value=payload.value,
        stage=payload.stage.value,
    )
    events_repo.log(
        db,
        project["id"],
        title="Project created",
        icon="sparkles",
        tone="ai",
        meta=project["name"],
    )
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    """Delete a project and all of its documents, quotes, RFQs and suppliers."""
    if not projects_repo.delete_project(db, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return None


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = _require_project(project_id, db)
    return {
        **project,
        "overviewCards": reference_repo.list_overview_cards(db),
        "packages": reference_repo.list_packages(db),
        "activity": events_repo.list_for_project(db, project_id),
    }


@router.get("/{project_id}/documents", response_model=List[Document])
def list_documents(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return documents_repo.list_for_project(db, project_id)


@router.get("/{project_id}/line-items", response_model=List[LineItemGroup])
def list_line_items(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return reference_repo.list_line_item_groups(db)


@router.get("/{project_id}/suppliers", response_model=List[Supplier])
def list_project_suppliers(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return suppliers_repo.list_suppliers(db)


@router.get("/{project_id}/quotes", response_model=List[Quote])
def list_quotes(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    # Prefer real ingested quotes; fall back to the demo quotes when none exist
    # (keeps the Riverside demo populated before any quotes are ingested).
    rows = quotes_repo.list_quote_rows(db, project_id)
    return rows if rows else reference_repo.list_demo_quotes(db)


@router.get("/{project_id}/rfqs", response_model=List[Rfq])
def list_rfqs(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return reference_repo.list_demo_rfqs(db)


@router.get("/{project_id}/rfq-folders", response_model=List[RfqFolder])
def list_rfq_folders(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return reference_repo.list_rfq_folders(db)


@router.get("/{project_id}/timeline", response_model=Timeline)
def get_timeline(project_id: str, db: Session = Depends(get_db)):
    _require_project(project_id, db)
    return reference_repo.get_timeline(db)


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
    # No ingested quotes yet → prototype demo comparison (keyed by label).
    comparison = reference_repo.get_comparison(db, pkg) or (
        reference_repo.get_comparison(db, label) if key else None
    )
    if comparison is None:
        raise HTTPException(status_code=404, detail="No comparison for package")
    return comparison


@router.get(
    "/{project_id}/packages/{pkg}/line-comparison", response_model=LineComparison
)
def get_line_comparison(project_id: str, pkg: str, db: Session = Depends(get_db)):
    """Line-by-line quote grid + freight-aware mix-and-match award strategies."""
    _require_project(project_id, db)
    key = pkg if packages.is_valid(pkg) else packages.category_for_label(pkg)
    label = packages.label_for(key) if key else pkg
    result = line_comparison_service.build_line_comparison(
        db, project_id, key or pkg, label
    )
    if result is None:
        raise HTTPException(status_code=404, detail="No quotes to compare for package")
    return result


@router.post("/{project_id}/packages/{pkg}/award", response_model=AwardResult)
def award_package(
    project_id: str, pkg: str, payload: AwardRequest, db: Session = Depends(get_db)
):
    """Submit a (possibly split) award for a package and issue the purchase orders."""
    _require_project(project_id, db)
    key = pkg if packages.is_valid(pkg) else packages.category_for_label(pkg)
    summary = line_comparison_service.compute_award(
        db, project_id, key or pkg, payload.selections
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="No quotes to award for package")
    quotes_repo.award_package(db, project_id, key or pkg, summary["supplierIds"])
    n = summary["poCount"]
    sup_list = ", ".join(summary["suppliers"])
    po_word = "PO" if n == 1 else "POs"
    pkg_label = packages.label_for(key) if key else pkg
    message = (
        f"Awarded {pkg_label} for "
        f"${summary['total']:,.0f} — {n} {po_word} to {sup_list}."
    )
    events_repo.log(
        db,
        project_id,
        title=f"{pkg_label} awarded to {sup_list}",
        icon="check",
        tone="success",
        meta=f"${summary['total']:,.0f} · {n} {po_word}",
    )
    return {
        "status": "awarded",
        "message": message,
        "total": summary["total"],
        "material": summary["material"],
        "freight": summary["freight"],
        "leadDays": summary["leadDays"],
        "suppliers": summary["suppliers"],
        "poCount": n,
    }


def _require_project(project_id: str, db: Session) -> dict:
    project = projects_repo.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
