"""Database accessors for award approval tokens.

Same split as invites: minting is org-scoped (the readiness check knows its
org); resolving is by token only, because the public approve route has no
authenticated org and derives it from the row.
"""
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.approval_token import ApprovalToken


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create(
    db: Session,
    org_id: str,
    *,
    project_id: str,
    package: str,
    package_label: str,
    payload: dict,
    ttl_days: Optional[int] = None,
) -> ApprovalToken:
    """Mint a pending token carrying the AwardRequest `payload`."""
    now = _utcnow()
    days = settings.approval_token_ttl_days if ttl_days is None else ttl_days
    row = ApprovalToken(
        id=uuid.uuid4().hex,
        organization_id=org_id,
        project_id=project_id,
        package=package,
        package_label=package_label,
        payload=json.dumps(payload),
        token=secrets.token_urlsafe(32),
        created_at=now,
        expires_at=now + timedelta(days=days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_by_token(db: Session, token: str) -> Optional[ApprovalToken]:
    """Resolve by secret token (public approve path). NOT org-scoped on purpose."""
    if not token:
        return None
    return db.scalar(select(ApprovalToken).where(ApprovalToken.token == token))


def mark_used(db: Session, row: ApprovalToken, decided_by_email: Optional[str]) -> ApprovalToken:
    row.used_at = _utcnow()
    row.decided_by_email = (decided_by_email or "").strip().lower() or None
    db.commit()
    db.refresh(row)
    return row
