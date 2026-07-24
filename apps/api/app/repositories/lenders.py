"""Database accessors for project lenders (financing contacts)."""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lender import Lender


def list_for_project(db: Session, project_id: str) -> List[dict]:
    rows = db.scalars(
        select(Lender).where(Lender.project_id == project_id).order_by(Lender.id)
    ).all()
    return [r.to_dict() for r in rows]


def create(
    db: Session,
    project_id: str,
    name: str,
    email: str,
    institution: str = "",
    phone: str = "",
) -> dict:
    lender = Lender(
        project_id=project_id,
        name=name.strip(),
        institution=institution.strip(),
        email=email.strip(),
        phone=phone.strip(),
    )
    db.add(lender)
    db.commit()
    db.refresh(lender)
    return lender.to_dict()


def delete(db: Session, project_id: str, lender_id: int) -> Optional[dict]:
    """Remove a lender; project-scoped so one project's ids can't delete
    another's rows. Returns the deleted payload, or None if not found."""
    lender = db.get(Lender, lender_id)
    if lender is None or lender.project_id != project_id:
        return None
    payload = lender.to_dict()
    db.delete(lender)
    db.commit()
    return payload
