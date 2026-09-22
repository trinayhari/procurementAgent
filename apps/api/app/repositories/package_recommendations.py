"""Database accessors for announced award recommendations (see the model)."""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.package_recommendation import PackageRecommendation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def live_for_package(
    db: Session, org_id: str, project_id: str, package: str
) -> Optional[PackageRecommendation]:
    """The recommendation currently standing for a package (not superseded)."""
    return db.scalars(
        select(PackageRecommendation)
        .where(
            PackageRecommendation.organization_id == org_id,
            PackageRecommendation.project_id == project_id,
            PackageRecommendation.package == package,
            PackageRecommendation.superseded_at.is_(None),
        )
        .order_by(PackageRecommendation.created_at.desc())
    ).first()


def record(
    db: Session,
    org_id: str,
    *,
    project_id: str,
    package: str,
    payload: dict,
    token_id: Optional[str],
) -> PackageRecommendation:
    """Store a new live recommendation, superseding any earlier one for the package."""
    now = _utcnow()
    for old in db.scalars(
        select(PackageRecommendation).where(
            PackageRecommendation.organization_id == org_id,
            PackageRecommendation.project_id == project_id,
            PackageRecommendation.package == package,
            PackageRecommendation.superseded_at.is_(None),
        )
    ).all():
        old.superseded_at = now
    row = PackageRecommendation(
        id=uuid.uuid4().hex,
        organization_id=org_id,
        project_id=project_id,
        package=package,
        payload=json.dumps(payload),
        token_id=token_id,
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def supersede(db: Session, org_id: str, project_id: str, package: str) -> int:
    """Close the live recommendation(s) for a package (e.g. once it is awarded)."""
    now = _utcnow()
    rows = db.scalars(
        select(PackageRecommendation).where(
            PackageRecommendation.organization_id == org_id,
            PackageRecommendation.project_id == project_id,
            PackageRecommendation.package == package,
            PackageRecommendation.superseded_at.is_(None),
        )
    ).all()
    for row in rows:
        row.superseded_at = now
    if rows:
        db.commit()
    return len(rows)
