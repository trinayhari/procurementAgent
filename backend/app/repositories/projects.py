"""Database-backed accessors for projects.

Projects are the one entity persisted to SQLite (via SQLAlchemy). The rest of the
workspace data (documents, suppliers, quotes, …) still comes from `seed.py` while
the prototype is fleshed out — those routes just validate the project exists here.
"""
import re
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.repositories import seed

# Stage -> badge tone, mirroring the frontend's stageToneMap.
_STAGE_TONE = {
    "Plans Review": "gray",
    "Sourcing": "blue",
    "RFQs Out": "blue",
    "Quotes In": "violet",
    "Complete": "success",
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "project"


def _unique_id(db: Session, base: str) -> str:
    pid, n = base, 2
    while db.get(Project, pid) is not None:
        pid = f"{base}-{n}"
        n += 1
    return pid


def _next_seq(db: Session) -> int:
    return (db.scalar(select(func.max(Project.seq))) or 0) + 1


def list_projects(db: Session) -> List[dict]:
    rows = db.scalars(select(Project).order_by(Project.seq.desc())).all()
    return [p.to_dict() for p in rows]


def get_project(db: Session, project_id: str) -> Optional[dict]:
    row = db.get(Project, project_id)
    return row.to_dict() if row else None


def create_project(
    db: Session,
    name: str,
    loc: str = "",
    value: str = "",
    stage: str = "Plans Review",
) -> dict:
    """Insert a new project (id derived from its name) and return its payload."""
    pid = _unique_id(db, _slugify(name))
    project = Project(
        seq=_next_seq(db),
        id=pid,
        name=name.strip(),
        loc=loc.strip() or "—",
        stage=stage,
        stage_tone=_STAGE_TONE.get(stage, "gray"),
        value=value.strip() or "$0",
        progress=0,
        suppliers=0,
        rfqs=0,
        quotes=0,
        risk="Low",
        risk_tone="success",
        bar_color="var(--primary)",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project.to_dict()


def seed_starter_projects(db: Session) -> None:
    """Populate the prototype's 5 demo projects once, on an empty table."""
    if db.scalar(select(func.count()).select_from(Project)):
        return
    # Insert reversed so the first seed project (Riverside) gets the highest seq
    # and therefore sorts to the top under ORDER BY seq DESC.
    for i, p in enumerate(reversed(seed.PROJECTS), start=1):
        db.add(
            Project(
                seq=i,
                id=p["id"],
                name=p["name"],
                loc=p["loc"],
                stage=p["stage"],
                stage_tone=p["stageTone"],
                value=p["value"],
                progress=p["progress"],
                suppliers=p["suppliers"],
                rfqs=p["rfqs"],
                quotes=p["quotes"],
                risk=p["risk"],
                risk_tone=p["riskTone"],
                bar_color=p["barColor"],
            )
        )
    db.commit()
