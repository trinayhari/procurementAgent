from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """An application user that can authenticate via email + password.

    Passwords are never stored in the clear — only the bcrypt hash lives in
    `password_hash`. `to_dict()` returns the public-safe shape (no hash)."""

    __tablename__ = "users"

    # Tenant boundary — every read/write filters on this explicitly.
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )

    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    company: Mapped[str] = mapped_column(String, nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    # Address Cc'd on outbound mail this user triggers (RFQ sends, award notices,
    # test emails), so they keep a copy. None → no Cc. This is NOT a From address:
    # everything is sent from the workspace mailbox (see services/rfq/sender.py).
    cc_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        """Public-safe payload — deliberately omits `password_hash`."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "company": self.company,
            "organizationId": self.organization_id,
            "ccEmail": self.cc_email,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
