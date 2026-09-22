"""Database-backed accessors for projects.

Every read and write is filtered on `org_id` explicitly. A project id is a slug
derived from its name, so ids are guessable across tenants — the filter (not the
id) is what keeps one organization's projects out of another's reach. Lookups
that miss the filter return None so routes 404 rather than 403 (a 403 would
confirm the row exists).
"""
import os
import re
from typing import List, Optional

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.event import ProjectEvent
from app.models.found_supplier import FoundSupplier
from app.models.lender import Lender
from app.models.project import Project
from app.models.quote import Quote
from app.models.rfq import Rfq
from app.models.timeline_event import TimelineEvent
from app.repositories import seed

def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "project"


def _unique_id(db: Session, base: str) -> str:
    # Deliberately unfiltered: `id` is the primary key, so it must be unique
    # across every organization, not just the caller's.
    pid, n = base, 2
    while db.get(Project, pid) is not None:
        pid = f"{base}-{n}"
        n += 1
    return pid


def _next_seq(db: Session) -> int:
    return (db.scalar(select(func.max(Project.seq))) or 0) + 1


def get_row(db: Session, org_id: str, project_id: str) -> Optional[Project]:
    """The ORM row, or None when it doesn't exist *or* belongs to another org."""
    row = db.get(Project, project_id)
    return row if row is not None and row.organization_id == org_id else None


def list_projects(db: Session, org_id: str) -> List[dict]:
    rows = db.scalars(
        select(Project)
        .where(Project.organization_id == org_id)
        .order_by(Project.seq.desc())
    ).all()
    return [p.to_dict() for p in rows]


def get_project(db: Session, org_id: str, project_id: str) -> Optional[dict]:
    row = get_row(db, org_id, project_id)
    return row.to_dict() if row else None


def create_project(
    db: Session,
    org_id: str,
    name: str,
    loc: str = "",
    value: str = "",
    need_by: Optional[str] = None,
) -> dict:
    """Insert a new project (id derived from its name) and return its payload."""
    pid = _unique_id(db, _slugify(name))
    project = Project(
        organization_id=org_id,
        seq=_next_seq(db),
        id=pid,
        name=name.strip(),
        loc=loc.strip() or "—",
        value=value.strip() or "$0",
        need_by=need_by or None,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project.to_dict()


_UPDATABLE = ("loc", "value", "need_by")


def update_project(db: Session, org_id: str, project_id: str, **fields) -> Optional[dict]:
    """Change a project's editable details (loc, value, need_by). A key that is
    present is applied even when None (clearing the need-by); absent keys are
    left alone. Returns the updated payload, or None when not found."""
    row = get_row(db, org_id, project_id)
    if row is None:
        return None
    for key, value in fields.items():
        if key not in _UPDATABLE:
            raise ValueError(f"{key} is not an editable project field")
        if key == "loc":
            value = (value or "").strip() or "—"
        elif key == "value":
            value = (value or "").strip() or "$0"
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row.to_dict()


def delete_project(db: Session, org_id: str, project_id: str) -> bool:
    """Delete a project and every row scoped to it.

    Removes the project's documents, quotes, RFQs and found-supplier records, and
    best-effort unlinks any uploaded files on disk. Returns False when the
    caller's organization has no project with that id (so the route can 404).
    """
    project = get_row(db, org_id, project_id)
    if project is None:
        return False
    # Grab uploaded file paths before the document rows are deleted.
    paths = [
        p
        for p in db.scalars(
            select(Document.source_path).where(
                Document.organization_id == org_id,
                Document.project_id == project_id,
            )
        ).all()
        if p
    ]
    for model in (Document, Quote, Rfq, FoundSupplier, ProjectEvent, TimelineEvent, Lender):
        db.execute(
            sa_delete(model).where(
                model.organization_id == org_id, model.project_id == project_id
            )
        )
    db.delete(project)
    db.commit()
    for path in paths:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass  # the records are already gone; leave the orphaned file
    return True


def seed_starter_projects(db: Session, org_id: str) -> None:
    """Populate the prototype's 5 demo projects once, into the demo org."""
    if db.scalar(select(func.count()).select_from(Project)):
        return
    # Insert reversed so the first seed project (Riverside) gets the highest seq
    # and therefore sorts to the top under ORDER BY seq DESC.
    for i, p in enumerate(reversed(seed.PROJECTS), start=1):
        db.add(
            Project(
                organization_id=org_id, seq=i, id=p["id"], name=p["name"],
                loc=p["loc"], value=p["value"],
            )
        )
    db.commit()
