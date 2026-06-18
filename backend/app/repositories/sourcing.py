"""Database accessors for found suppliers + the per-project geocode cache."""
import json
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.found_supplier import FoundSupplier
from app.models.project import Project


def replace_found_suppliers(
    db: Session, project_id: str, package: str, results: List[dict]
) -> List[dict]:
    """Delete the prior search for (project, package) and insert the new results."""
    db.execute(
        delete(FoundSupplier).where(
            FoundSupplier.project_id == project_id,
            FoundSupplier.package == package,
        )
    )
    rows: List[FoundSupplier] = []
    for r in results:
        row = FoundSupplier(
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
        )
        rows.append(row)
        db.add(row)
    db.commit()
    return [r.to_dict() for r in rows]


def list_found_suppliers(
    db: Session, project_id: str, package: Optional[str] = None
) -> List[dict]:
    stmt = select(FoundSupplier).where(FoundSupplier.project_id == project_id)
    if package:
        stmt = stmt.where(FoundSupplier.package == package)
    stmt = stmt.order_by(FoundSupplier.distance_miles)
    return [r.to_dict() for r in db.scalars(stmt).all()]


def get_found_supplier(db: Session, supplier_id: str) -> Optional[dict]:
    row = db.get(FoundSupplier, supplier_id)
    return row.to_dict() if row else None


def get_found_suppliers_by_ids(db: Session, ids: List[str]) -> List[dict]:
    if not ids:
        return []
    rows = db.scalars(
        select(FoundSupplier).where(FoundSupplier.id.in_(ids))
    ).all()
    return [r.to_dict() for r in rows]


# ----------------------------------------------------------- geocode cache
def get_cached_latlng(db: Session, project_id: str, loc: str) -> Optional[Tuple[float, float]]:
    """Return the cached (lat,lng) only if it was geocoded from the current loc."""
    row = db.get(Project, project_id)
    if row and row.lat is not None and row.lng is not None and row.geocoded_loc == loc:
        return (row.lat, row.lng)
    return None


def cache_latlng(db: Session, project_id: str, loc: str, lat: float, lng: float) -> None:
    row = db.get(Project, project_id)
    if row is None:
        return
    row.lat = lat
    row.lng = lng
    row.geocoded_loc = loc
    db.commit()
