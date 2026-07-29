"""Database accessors for organizations (the tenant boundary).

There is no cross-organization read here by design: an org is only ever looked
up by its own id, and rows are only created by the register flow.
"""
import re
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization

# Last-resort name when we can't derive anything from the signup payload.
DEFAULT_ORG_NAME = "New Organization"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "org"


def _unique_id(db: Session, base: str) -> str:
    """Pick a slug id not already taken (base, base-2, base-3, …)."""
    candidate = base
    n = 2
    while db.get(Organization, candidate) is not None:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _next_seq(db: Session) -> int:
    return (db.scalar(select(func.max(Organization.seq))) or 0) + 1


def org_name_for_signup(company: str = "", email: str = "", name: str = "") -> str:
    """Best available name for the organization a signup creates.

    Prefers the company the user typed; falls back to their email domain
    (``dana@acme.com`` → ``Acme``), then to ``"{name}'s Organization"``, then to
    a generic default — so an org always has something human-readable.
    """
    company = (company or "").strip()
    if company:
        return company
    domain = (email or "").strip().rsplit("@", 1)[-1] if "@" in (email or "") else ""
    label = domain.split(".")[0].strip() if domain else ""
    if label:
        return label.replace("-", " ").replace("_", " ").title()
    name = (name or "").strip()
    if name:
        return f"{name}'s Organization"
    return DEFAULT_ORG_NAME


def get_organization(db: Session, org_id: str) -> Optional[Organization]:
    return db.get(Organization, org_id)


def create_organization(db: Session, name: str, org_id: Optional[str] = None) -> Organization:
    """Insert a new organization (id derived from its name unless given)."""
    clean = (name or "").strip() or DEFAULT_ORG_NAME
    org = Organization(
        seq=_next_seq(db),
        id=org_id or _unique_id(db, _slugify(clean)),
        name=clean,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def ensure_organization(db: Session, org_id: str, name: str) -> Organization:
    """Get-or-create by explicit id — used by seeding and the `default` org."""
    existing = db.get(Organization, org_id)
    if existing is not None:
        return existing
    return create_organization(db, name, org_id=org_id)
