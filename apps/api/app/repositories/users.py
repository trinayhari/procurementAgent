"""Database accessors for application users + auth helpers.

A user belongs to exactly one organization (``organization_id``), and that value
is what every other repository filters on. Lookups by id/email are deliberately
NOT org-filtered: they resolve the caller's own identity (bearer token, login),
which is what an organization is then derived from.
"""
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
    """Resolve a bearer token's subject. Not org-filtered — this call is how the
    caller's organization is established in the first place."""
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> Optional[User]:
    """Look a user up for login / duplicate-registration checks.

    Not org-filtered: email is globally unique across the deployment, so this
    has to see every organization to reject a duplicate signup."""
    normalized = email.strip().lower()
    return db.scalar(select(User).where(func.lower(User.email) == normalized))


def list_for_org(db: Session, org_id: str) -> list:
    """Every user in an organization (the team roster), oldest-first by seq."""
    return list(
        db.scalars(
            select(User).where(User.organization_id == org_id).order_by(User.seq)
        ).all()
    )


def create_user(
    db: Session,
    org_id: str,
    email: str,
    password: str,
    name: str = "",
    company: str = "",
) -> User:
    """Insert a new user, hashed password, into `org_id`. Caller must ensure the
    email is not already registered (see get_by_email).

    Two callers attach a user to an org: register (which makes a fresh org per
    signup) and the invite-accept flow (which passes the inviting org's id, so
    teammates share one organization). See app/api/routes/team.py.
    """
    email = email.strip().lower()
    user = User(
        organization_id=org_id,
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


def set_cc_email(db: Session, user: User, cc_email: Optional[str]) -> User:
    """Set (or clear, with None) the address Cc'd on this user's outgoing mail."""
    user.cc_email = cc_email.strip().lower() if cc_email else None
    db.commit()
    db.refresh(user)
    return user


def seed_demo_user(db: Session, org_id: str) -> None:
    """Seed the prototype's demo account so login works on a fresh checkout.

    Credentials: jordan@meridiancivil.com / procureai. Idempotent."""
    if get_by_email(db, "jordan@meridiancivil.com") is None:
        create_user(
            db,
            org_id,
            email="jordan@meridiancivil.com",
            password="procureai",
            name="Jordan Mills",
            company="Meridian Civil Co.",
        )
