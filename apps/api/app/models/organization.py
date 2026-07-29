"""ORM model for the tenant boundary.

An organization owns every row a customer can see. One is created per signup
(named from the registering user's `company`); users belong to exactly one, and
every tenant-scoped table carries an `organization_id` FK back to here. Filtering
is explicit in the repositories rather than a session-level hook — an implicit
filter fails open the day someone adds a query and forgets it.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    # Monotonic insertion-order key (assigned by the repo), matching the other
    # slug-id tables.
    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        """Shape a row into the camelCase payload the API schemas expect."""
        return {
            "id": self.id,
            "name": self.name,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
