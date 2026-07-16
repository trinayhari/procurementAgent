import json
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BackgroundJob(Base):
    """Durable record of one background task (supplier search, quote ingest).

    Replaces the old module-level status dicts: job state survives restarts and
    is visible from every worker process. Failed jobs form the operator-facing
    exception queue (GET /api/jobs?status=error) and can be retried.
    """

    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Entity key the job belongs to — "{project_id}:{package}" for searches,
    # the project id for ingests. The latest job per (kind, ref) is the one
    # pollers report on.
    ref: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "ref": self.ref,
            "status": self.status,
            "detail": json.loads(self.detail or "{}"),
            "error": self.error,
            "attempts": self.attempts,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
