"""Database accessors for found suppliers + the per-project geocode cache.

Search results are customer data (who we found, their contacts), so every read
and write is filtered on `org_id`.
"""
import json
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.found_supplier import FoundSupplier
from app.models.project import Project


def replace_found_suppliers(
    db: Session, org_id: str, project_id: str, package: str, results: List[dict]
) -> List[dict]:
    """Delete the prior search for (project, package) and insert the new results."""
    db.execute(
        delete(FoundSupplier).where(
            FoundSupplier.organization_id == org_id,
            FoundSupplier.project_id == project_id,
            FoundSupplier.package == package,
        )
    )
    rows: List[FoundSupplier] = []
    for r in results:
        row = FoundSupplier(
            organization_id=org_id,
            id=uuid.uuid4().hex,
            project_id=project_id,
            package=package,
            name=r.get("name", ""),
            address=r.get("address", ""),
            distance_miles=float(r.get("distance_miles", 0.0)),
            tier=int(r.get("tier", 0)),
            contact_name=r.get("contact_name"),
            email=r.get("email"),
            phone=r.get("phone"),
            website=r.get("website"),
            material_categories=json.dumps(r.get("material_categories", [])),
            email_source=r.get("email_source", "none"),
            place_id=r.get("place_id"),
            relevance_score=float(r.get("relevance_score", 1.0)),
            verify_reason=r.get("verify_reason", ""),
        )
        rows.append(row)
        db.add(row)
    db.commit()
    return [r.to_dict() for r in rows]


def list_found_suppliers(
    db: Session, org_id: str, project_id: str, package: Optional[str] = None
) -> List[dict]:
    stmt = select(FoundSupplier).where(
        FoundSupplier.organization_id == org_id,
        FoundSupplier.project_id == project_id,
    )
    if package:
        stmt = stmt.where(FoundSupplier.package == package)
    stmt = stmt.order_by(
        FoundSupplier.relevance_score.desc(),
        FoundSupplier.distance_miles,
    )
    return [r.to_dict() for r in db.scalars(stmt).all()]


def get_found_supplier(db: Session, org_id: str, supplier_id: str) -> Optional[dict]:
    row = db.get(FoundSupplier, supplier_id)
    if row is None or row.organization_id != org_id:
        return None
    return row.to_dict()


def get_found_suppliers_by_ids(db: Session, org_id: str, ids: List[str]) -> List[dict]:
    if not ids:
        return []
    rows = db.scalars(
        select(FoundSupplier).where(
            FoundSupplier.organization_id == org_id,
            FoundSupplier.id.in_(ids),
        )
    ).all()
    return [r.to_dict() for r in rows]


# ----------------------------------------------------------- geocode cache
def get_cached_latlng(
    db: Session, org_id: str, project_id: str, loc: str
) -> Optional[Tuple[float, float]]:
    """Return the cached (lat,lng) only if it was geocoded from the current loc."""
    row = db.get(Project, project_id)
    if row is None or row.organization_id != org_id:
        return None
    if row.lat is not None and row.lng is not None and row.geocoded_loc == loc:
        return (row.lat, row.lng)
    return None


def cache_latlng(
    db: Session, org_id: str, project_id: str, loc: str, lat: float, lng: float
) -> None:
    row = db.get(Project, project_id)
    if row is None or row.organization_id != org_id:
        return
    row.lat = lat
    row.lng = lng
    row.geocoded_loc = loc
    db.commit()
