"""ORM model for the per-project activity stream.

Unlike the seeded ``activity_items`` table (which backs the global dashboard
feed), these rows are *real* events appended as the user works a project —
uploading plans, extracting BOMs, sourcing suppliers, sending RFQs, ingesting
quotes, awarding packages. Each carries a real UTC timestamp so the API can
render a relative "12m / 2d" label rather than a frozen seed string.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectEvent(Base):
    __tablename__ = "project_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Scopes the event to a project; indexed for the newest-first list query.
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # icon/tone mirror the dashboard Activity fields so the same row renderer works.
    icon: Mapped[str] = mapped_column(String, nullable=False, default="file")
    tone: Mapped[str] = mapped_column(String, nullable=False, default="blue")
    title: Mapped[str] = mapped_column(String, nullable=False)
    meta: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
