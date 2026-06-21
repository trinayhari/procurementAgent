"""Database accessors for application users + auth helpers."""
import re
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "user"


def _unique_id(db: Session, base: str) -> str:
    """Pick a slug id not already taken (base, base-2, base-3, …)."""
    candidate = base
    n = 2
    while db.get(User, candidate) is not None:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _next_seq(db: Session) -> int:
    return (db.scalar(select(func.max(User.seq))) or 0) + 1


def get_user(db: Session, user_id: str) -> Optional[User]:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> Optional[User]:
    normalized = email.strip().lower()
    return db.scalar(select(User).where(func.lower(User.email) == normalized))


def create_user(
    db: Session, email: str, password: str, name: str = "", company: str = ""
) -> User:
    """Insert a new user with a hashed password. Caller must ensure the email
    is not already registered (see get_by_email)."""
    email = email.strip().lower()
    user = User(
        seq=_next_seq(db),
        id=_unique_id(db, _slugify(name or email.split("@")[0])),
        email=email,
        name=name.strip(),
        company=company.strip(),
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_demo_user(db: Session) -> None:
    """Seed the prototype's demo account so login works on a fresh checkout.

    Credentials: jordan@meridiancivil.com / procureai. Idempotent."""
    if get_by_email(db, "jordan@meridiancivil.com") is None:
        create_user(
            db,
            email="jordan@meridiancivil.com",
            password="procureai",
            name="Jordan Mills",
            company="Meridian Civil Co.",
        )
