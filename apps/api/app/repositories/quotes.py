"""Database accessors for ingested supplier quotes.

Quote ids are uuids, but every lookup is still filtered on `org_id` so a quote
belonging to another tenant is indistinguishable from one that doesn't exist.
"""
import json
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.quote import Quote


def _get_row(db: Session, org_id: str, quote_id: str) -> Optional[Quote]:
    """The ORM row, or None when it doesn't exist *or* belongs to another org."""
    row = db.get(Quote, quote_id)
    return row if row is not None and row.organization_id == org_id else None


def create_quote(db: Session, org_id: str, **fields) -> dict:
    line_items = fields.pop("line_items", [])
    row = Quote(
        organization_id=org_id,
        id=uuid.uuid4().hex,
        line_items=json.dumps(line_items),
        **fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


def get_quote(db: Session, org_id: str, quote_id: str) -> Optional[dict]:
    row = _get_row(db, org_id, quote_id)
    return row.to_dict() if row else None


def list_quotes(
    db: Session, org_id: str, project_id: str, package: Optional[str] = None
) -> List[dict]:
    stmt = select(Quote).where(
        Quote.organization_id == org_id, Quote.project_id == project_id
    )
    if package:
        stmt = stmt.where(Quote.package == package)
    stmt = stmt.order_by(Quote.total.is_(None), Quote.total)
    return [r.to_dict() for r in db.scalars(stmt).all()]


def list_quote_rows(db: Session, org_id: str, project_id: str) -> List[dict]:
    """All quotes for a project shaped for the Quotes table UI, cheapest-best flagged per package."""
    stmt = (
        select(Quote)
        .where(Quote.organization_id == org_id, Quote.project_id == project_id)
        .order_by(Quote.total.is_(None), Quote.total)
    )
    rows = list(db.scalars(stmt).all())
    # Flag the lowest total per package as "best".
    best_by_pkg: dict = {}
    for r in rows:
        if r.total is None:
            continue
        cur = best_by_pkg.get(r.package)
        if cur is None or r.total < cur[1]:
            best_by_pkg[r.package] = (r.id, r.total)
    best_ids = {v[0] for v in best_by_pkg.values()}
    return [r.to_quote_row(best=r.id in best_ids) for r in rows]


def seed_sample_quotes(db: Session, org_id: str, project_id: str) -> int:
    """Seed priced sample quotes for a project's demo packages (idempotent).

    Skips any package that already has quotes, so real ingested quotes are never
    overwritten. Returns the number of quotes created.
    """
    from app.services.quotes.sample_data import SAMPLE_PACKAGES, build_quote_payloads

    created = 0
    for package_key in SAMPLE_PACKAGES:
        existing = db.scalars(
            select(Quote.id).where(
                Quote.organization_id == org_id,
                Quote.project_id == project_id,
                Quote.package == package_key,
            )
        ).first()
        if existing is not None:
            continue
        for payload in build_quote_payloads(package_key):
            create_quote(db, org_id, project_id=project_id, **payload)
            created += 1
    return created


def award_package(
    db: Session, org_id: str, project_id: str, package: str, supplier_ids: set
) -> int:
    """Mark the winning suppliers' quotes as selected for a package (split-award aware).

    Every supplier that won at least one line is 'selected'; the rest revert to
    'received'. Returns the number of quotes marked selected.
    """
    quotes = db.scalars(
        select(Quote).where(
            Quote.organization_id == org_id,
            Quote.project_id == project_id,
            Quote.package == package,
        )
    ).all()
    selected = 0
    for q in quotes:
        if q.supplier_id in supplier_ids or q.supplier_name in supplier_ids:
            q.status = "selected"
            selected += 1
        else:
            q.status = "received"
    db.commit()
    return selected


def message_ids_for_project(db: Session, org_id: str, project_id: str) -> set:
    """Gmail message ids already ingested for this project (for dedupe)."""
    rows = db.scalars(
        select(Quote.source_message_id).where(
            Quote.organization_id == org_id,
            Quote.project_id == project_id,
            Quote.source_message_id.isnot(None),
        )
    ).all()
    return {r for r in rows if r}


def has_quote_for_recipient(
    db: Session, org_id: str, project_id: str, package: str, email: str
) -> bool:
    row = db.scalars(
        select(Quote.id).where(
            Quote.organization_id == org_id,
            Quote.project_id == project_id,
            Quote.package == package,
            Quote.supplier_email == email,
        )
    ).first()
    return row is not None


def select_quote(db: Session, org_id: str, quote_id: str) -> Optional[dict]:
    """Mark one quote selected; un-select its package siblings."""
    row = _get_row(db, org_id, quote_id)
    if row is None:
        return None
    siblings = db.scalars(
        select(Quote).where(
            Quote.organization_id == org_id,
            Quote.project_id == row.project_id,
            Quote.package == row.package,
        )
    ).all()
    for s in siblings:
        s.status = "selected" if s.id == quote_id else "received"
    db.commit()
    db.refresh(row)
    return row.to_dict()
