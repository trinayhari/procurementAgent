"""ORM model for a single-use award approval link.

When a package is ready to award (see services/rfq/readiness.py) the agent
mints one of these and puts `#/approve/<token>` in the award.ready notice.
`payload` is the AwardRequest the recommendation would submit; POSTing the
token runs the same award path as the dashboard with exactly that payload.
Resolved by token alone on the public route (no org context there), the org
is derived FROM the row, so a token can never award outside its own tenant.

Lifecycle: pending until `used_at` is set or `expires_at` passes.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    # SQLite hands back naive timestamps; treat them as UTC for comparisons.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class ApprovalToken(Base):
    __tablename__ = "approval_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid hex
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    package: Mapped[str] = mapped_column(String, nullable=False)
    package_label: Mapped[str] = mapped_column(String, nullable=False, default="")
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON AwardRequest
    # The approve secret (secrets.token_urlsafe). Unique + indexed so the public
    # route can resolve it alone.
    token: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decided_by_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    def status(self, now: Optional[datetime] = None) -> str:
        """"pending" | "used" | "expired"."""
        if self.used_at is not None:
            return "used"
        now = now or _utcnow()
        return "pending" if _as_utc(self.expires_at) > now else "expired"

    def award_request(self) -> dict:
        return json.loads(self.payload or "{}")
