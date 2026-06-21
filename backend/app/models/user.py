from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """An application user that can authenticate via email + password.

    Passwords are never stored in the clear — only the bcrypt hash lives in
    `password_hash`. `to_dict()` returns the public-safe shape (no hash)."""

    __tablename__ = "users"

    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    company: Mapped[str] = mapped_column(String, nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        """Public-safe payload — deliberately omits `password_hash`."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "company": self.company,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
