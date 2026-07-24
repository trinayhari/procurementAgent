import json
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditEvent(Base):
    """Append-only audit trail: who did what, to which entity, when.

    Distinct from `project_events` (the UI activity feed): audit events record
    the acting user and structured detail, are never edited or deleted, and
    cover consequential actions across the whole workflow. There is
    deliberately no update/delete accessor for this table.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String, nullable=False, default="system")
    actor_email: Mapped[str] = mapped_column(String, nullable=False, default="system")
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    entity_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    project_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "actorId": self.actor_id,
            "actorEmail": self.actor_email,
            "action": self.action,
            "entityType": self.entity_type,
            "entityId": self.entity_id,
            "projectId": self.project_id,
            "detail": json.loads(self.detail or "{}"),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
