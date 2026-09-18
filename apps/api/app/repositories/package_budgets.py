"""Database accessors for per-package budgets (see models/package_budget.py)."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.package_budget import PackageBudget


def _row(db: Session, org_id: str, project_id: str, package: str) -> Optional[PackageBudget]:
    return db.scalars(
        select(PackageBudget).where(
            PackageBudget.organization_id == org_id,
            PackageBudget.project_id == project_id,
            PackageBudget.package == package,
        )
    ).first()


def get_budget(db: Session, org_id: str, project_id: str, package: str) -> Optional[float]:
    """The budget set for a package, or None when none has been set."""
    row = _row(db, org_id, project_id, package)
    return float(row.budget) if row is not None else None


def set_budget(
    db: Session, org_id: str, project_id: str, package: str, budget: Optional[float]
) -> Optional[float]:
    """Set (or, with None, clear) a package's budget. Returns the stored value."""
    row = _row(db, org_id, project_id, package)
    if budget is None:
        if row is not None:
            db.delete(row)
            db.commit()
        return None
    if row is None:
        row = PackageBudget(
            organization_id=org_id, project_id=project_id, package=package, budget=float(budget)
        )
        db.add(row)
    else:
        row.budget = float(budget)
    db.commit()
    return float(row.budget)
