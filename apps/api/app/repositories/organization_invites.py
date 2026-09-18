"""Database accessors for team invitations.

Two access patterns, mirroring how users are looked up:
- Management (create / list / revoke) is **org-scoped** — a member only ever
  touches their own organization's invites; a foreign id resolves to None so the
  route can 404.
- Accept is by **token only** and is deliberately NOT org-scoped: the public
  accept endpoint has no authenticated org context — it derives the org FROM the
  invite it resolves.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization_invite import OrganizationInvite

DEFAULT_TTL_DAYS = 7


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_seq(db: Session) -> int:
    return (db.scalar(select(func.max(OrganizationInvite.seq))) or 0) + 1


def get_pending_for_email(db: Session, org_id: str, email: str) -> Optional[OrganizationInvite]:
    """An existing live (pending, unexpired) invite to `email` in this org, if any.

    Lets the create path be idempotent instead of piling up duplicate invites for
    the same person."""
    email = email.strip().lower()
    rows = db.scalars(
        select(OrganizationInvite).where(
            OrganizationInvite.organization_id == org_id,
            func.lower(OrganizationInvite.email) == email,
            OrganizationInvite.status == "pending",
        )
    ).all()
    for row in rows:
        if row.is_live():
            return row
    return None


def create_invite(
    db: Session, org_id: str, email: str, invited_by_user_id: str, ttl_days: int = DEFAULT_TTL_DAYS
) -> OrganizationInvite:
    """Mint a pending invite with a fresh secret token. Callers must first reject
    an email that already belongs to a registered user (see users_repo)."""
    now = _utcnow()
    invite = OrganizationInvite(
        seq=_next_seq(db),
        id=uuid.uuid4().hex,
        organization_id=org_id,
        email=email.strip().lower(),
        token=secrets.token_urlsafe(32),
        invited_by_user_id=invited_by_user_id,
        status="pending",
        created_at=now,
        expires_at=now + timedelta(days=ttl_days),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def list_pending(db: Session, org_id: str) -> List[OrganizationInvite]:
    """Live invites for the org's team page (pending and not yet expired), newest first."""
    rows = db.scalars(
        select(OrganizationInvite)
        .where(
            OrganizationInvite.organization_id == org_id,
            OrganizationInvite.status == "pending",
        )
        .order_by(OrganizationInvite.seq.desc())
    ).all()
    return [r for r in rows if r.is_live()]


def get_scoped(db: Session, org_id: str, invite_id: str) -> Optional[OrganizationInvite]:
    """An invite by id, or None when it doesn't exist OR belongs to another org."""
    row = db.get(OrganizationInvite, invite_id)
    return row if row is not None and row.organization_id == org_id else None


def revoke(db: Session, org_id: str, invite_id: str) -> Optional[OrganizationInvite]:
    """Cancel a pending invite. Returns the row, or None if not found / not this
    org's / not pending."""
    invite = get_scoped(db, org_id, invite_id)
    if invite is None or invite.status != "pending":
        return None
    invite.status = "revoked"
    db.commit()
    db.refresh(invite)
    return invite


def get_by_token(db: Session, token: str) -> Optional[OrganizationInvite]:
    """Resolve an invite by its secret token (public accept path). NOT org-scoped
    on purpose — the accept flow has no org context and derives it from here."""
    if not token:
        return None
    return db.scalar(select(OrganizationInvite).where(OrganizationInvite.token == token))


def mark_accepted(db: Session, invite: OrganizationInvite) -> OrganizationInvite:
    """Flip a live invite to accepted once its user has been created."""
    invite.status = "accepted"
    invite.accepted_at = _utcnow()
    db.commit()
    db.refresh(invite)
    return invite
