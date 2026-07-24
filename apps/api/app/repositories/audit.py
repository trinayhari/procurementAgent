"""Append-only accessors for the audit trail.

There is intentionally no update or delete here — audit events are immutable.
"""
import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.user import User


def log(
    db: Session,
    actor: Optional[User],
    action: str,
    entity_type: str = "",
    entity_id: str = "",
    project_id: Optional[str] = None,
    detail: Optional[dict] = None,
    commit: bool = True,
) -> None:
    """Record one audit event. Pass commit=False to join the caller's transaction
    (e.g. so an award and its audit record commit atomically)."""
    db.add(
        AuditEvent(
            actor_id=actor.id if actor else "system",
            actor_email=actor.email if actor else "system",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
            detail=json.dumps(detail or {}),
        )
    )
    if commit:
        db.commit()


def list_events(
    db: Session,
    project_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 200,
) -> List[dict]:
    stmt = select(AuditEvent)
    if project_id:
        stmt = stmt.where(AuditEvent.project_id == project_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    stmt = stmt.order_by(AuditEvent.id.desc()).limit(limit)
    return [r.to_dict() for r in db.scalars(stmt).all()]
