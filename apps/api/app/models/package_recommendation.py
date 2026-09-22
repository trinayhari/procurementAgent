"""ORM model for an announced award recommendation.

One row per award.ready notice the agent sent for a package: which quotes it
was computed over (`quote_ids`, sorted, in the payload) and the approval token
that went with it. Readiness checks this before announcing again, so a second
ingest pass over the same replies never re-sends the award card; a new quote
supersedes the old row and a fresh recommendation goes out.
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PackageRecommendation(Base):
    __tablename__ = "package_recommendations"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid hex
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    package: Mapped[str] = mapped_column(String, nullable=False)
    # JSON: the Recommendation as announced (award request, totals, quoteIds).
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    token_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    superseded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def quote_ids(self) -> List[str]:
        return sorted(json.loads(self.payload or "{}").get("quoteIds") or [])
