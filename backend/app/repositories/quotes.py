"""Database accessors for ingested supplier quotes."""
import json
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.quote import Quote


def create_quote(db: Session, **fields) -> dict:
    line_items = fields.pop("line_items", [])
    row = Quote(
        id=uuid.uuid4().hex,
        line_items=json.dumps(line_items),
        **fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


def get_quote(db: Session, quote_id: str) -> Optional[dict]:
    row = db.get(Quote, quote_id)
    return row.to_dict() if row else None


def list_quotes(
    db: Session, project_id: str, package: Optional[str] = None
) -> List[dict]:
    stmt = select(Quote).where(Quote.project_id == project_id)
    if package:
        stmt = stmt.where(Quote.package == package)
    stmt = stmt.order_by(Quote.total.is_(None), Quote.total)
    return [r.to_dict() for r in db.scalars(stmt).all()]


def list_quote_rows(db: Session, project_id: str) -> List[dict]:
    """All quotes for a project shaped for the Quotes table UI, cheapest-best flagged per package."""
    stmt = (
        select(Quote)
        .where(Quote.project_id == project_id)
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


def message_ids_for_project(db: Session, project_id: str) -> set:
    """Gmail message ids already ingested for this project (for dedupe)."""
    rows = db.scalars(
        select(Quote.source_message_id).where(
            Quote.project_id == project_id, Quote.source_message_id.isnot(None)
        )
    ).all()
    return {r for r in rows if r}


def has_quote_for_recipient(db: Session, project_id: str, package: str, email: str) -> bool:
    row = db.scalars(
        select(Quote.id).where(
            Quote.project_id == project_id,
            Quote.package == package,
            Quote.supplier_email == email,
        )
    ).first()
    return row is not None


def select_quote(db: Session, quote_id: str) -> Optional[dict]:
    """Mark one quote selected; un-select its package siblings."""
    row = db.get(Quote, quote_id)
    if row is None:
        return None
    siblings = db.scalars(
        select(Quote).where(
            Quote.project_id == row.project_id, Quote.package == row.package
        )
    ).all()
    for s in siblings:
        s.status = "selected" if s.id == quote_id else "received"
    db.commit()
    db.refresh(row)
    return row.to_dict()
