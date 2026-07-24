"""Database accessors for the per-project activity stream.

``log()`` appends a real event as the user works a project; ``list_for_project``
reads them back newest-first and renders each timestamp as a compact relative
label ("just now", "12m", "3h", "2d", "Apr 14") for the Activity row UI.
"""
from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event import ProjectEvent
from app.models.project import Project


def _relative_time(then: datetime, now: datetime) -> str:
    """Compact "12m / 3h / 2d" label for an event timestamp (UTC-naive)."""
    secs = max(0, int((now - then).total_seconds()))
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 7:
        return f"{days}d"
    if days < 365:
        return f"{weeks}w" if (weeks := days // 7) < 5 else then.strftime("%b %-d")
    return then.strftime("%b %-d, %Y")


def log(
    db: Session,
    project_id: str,
    *,
    title: str,
    icon: str = "file",
    tone: str = "blue",
    meta: str = "",
) -> None:
    """Append one activity event for a project. Best-effort: never raises into
    the caller's flow (a failed event log must not break an upload/award/etc.)."""
    try:
        db.add(
            ProjectEvent(
                project_id=project_id, icon=icon, tone=tone, title=title, meta=meta
            )
        )
        db.commit()
    except Exception:  # pragma: no cover - activity logging is non-critical
        db.rollback()


def list_for_project(db: Session, project_id: str, limit: int = 30) -> List[dict]:
    """Newest-first activity events for a project, shaped for the Activity schema."""
    rows = db.scalars(
        select(ProjectEvent)
        .where(ProjectEvent.project_id == project_id)
        .order_by(ProjectEvent.created_at.desc(), ProjectEvent.id.desc())
        .limit(limit)
    ).all()
    now = datetime.utcnow()
    return [
        {
            "icon": e.icon,
            "tone": e.tone,
            "title": e.title,
            "meta": e.meta,
            "time": _relative_time(e.created_at, now),
        }
        for e in rows
    ]


def list_recent(db: Session, limit: int = 8) -> List[dict]:
    """Newest events across *all* projects, for the global dashboard feed.

    Same shape as ``list_for_project`` but each row's meta is prefixed with the
    project name so the aggregated feed shows which project each event belongs
    to. Deliberately capped small (default 8) — the dashboard is a glance, not
    an audit log; the full stream lives on each project's Overview tab.
    """
    rows = db.execute(
        select(ProjectEvent, Project.name)
        .join(Project, Project.id == ProjectEvent.project_id)
        .order_by(ProjectEvent.created_at.desc(), ProjectEvent.id.desc())
        .limit(limit)
    ).all()
    now = datetime.utcnow()
    return [
        {
            "icon": e.icon,
            "tone": e.tone,
            "title": e.title,
            "meta": f"{name} · {e.meta}" if e.meta else name,
            "time": _relative_time(e.created_at, now),
        }
        for e, name in rows
    ]
