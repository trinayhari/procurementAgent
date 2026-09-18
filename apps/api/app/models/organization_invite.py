"""ORM model for a pending team invitation.

An org member invites a teammate by email; the invite carries a secret `token`
(the accept link) and belongs to the inviting `organization_id`. Accepting it
creates a user in THAT org — the one place, besides register (which makes a new
org), that a user is attached to an organization.

Lifecycle: `pending` → `accepted` (a user was created) or `revoked` (cancelled
by a member). An invite past `expires_at` is dead even while still `pending`.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrganizationInvite(Base):
    __tablename__ = "organization_invites"

    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid hex
    # The org the invitee will join. Scoped reads/writes filter on this.
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # The accept secret (secrets.token_urlsafe). Unique + indexed so the public
    # accept route can resolve an invite by token alone (it has no org context).
    token: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    invited_by_user_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def is_live(self, now: Optional[datetime] = None) -> bool:
        """Still acceptable: pending and not past expiry."""
        now = now or _utcnow()
        expires = self.expires_at
        # A naive timestamp from SQLite is treated as UTC for the comparison.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return self.status == "pending" and expires > now

    def to_dict(self) -> dict:
        """Public-safe payload for the team UI — deliberately omits `token`."""
        return {
            "id": self.id,
            "email": self.email,
            "status": self.status,
            "invitedByUserId": self.invited_by_user_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "acceptedAt": self.accepted_at.isoformat() if self.accepted_at else None,
        }
