"""Approval links: preview and execute an award from a single-use token.

The token is the credential (the approver may have no account: the card
landed in email or Slack). Everything is derived from the token row, so a
link minted in one org can only ever award in that org. `execute` runs the
exact award path the dashboard uses (services/awards.py) and is callable
in-process by the Slack interaction handler as well as by the HTTP route.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.approval_token import ApprovalToken
from app.repositories import approval_tokens as tokens_repo
from app.repositories import organizations as organizations_repo
from app.repositories import projects as projects_repo
from app.repositories import purchase_decisions as purchase_decisions_repo
from app.repositories import users as users_repo
from app.schemas.quote import AwardRequest
from app.services import awards
from app.services.rfq import readiness


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _load(db: Session, token: str) -> ApprovalToken:
    row = tokens_repo.get_by_token(db, token)
    if row is None:
        raise HTTPException(status_code=404, detail="This approval link is not valid")
    return row


def preview(db: Session, token: str) -> dict:
    """What the approve page shows. Figures are computed live for the token's
    selections, so the card always reflects the quotes as they stand."""
    row = _load(db, token)
    project = projects_repo.get_project(db, row.organization_id, row.project_id) or {}
    award = row.award_request()
    rec = readiness.describe(
        db, row.organization_id, row.project_id, row.package,
        selections=award.get("selections") or {},
    )
    latest = purchase_decisions_repo.latest_for_package(
        db, row.organization_id, row.project_id, row.package
    )
    out = {
        "status": row.status(),
        "projectId": row.project_id,
        "projectName": project.get("name") or "Project",
        "package": row.package,
        "packageLabel": row.package_label or (rec.package_label if rec else row.package),
        "expiresAt": _iso(row.expires_at),
        "decidedAt": _iso(row.used_at),
        "decidedByEmail": row.decided_by_email,
        "alreadyAwarded": latest is not None and row.used_at is None,
    }
    if rec is not None:
        out.update({
            "suppliers": rec.suppliers,
            "total": rec.total,
            "material": rec.material,
            "freight": rec.freight,
            "leadDays": rec.lead_days,
            "savings": rec.savings,
            "quotesReceived": rec.quotes_received,
            "recipientsTotal": rec.recipients_total,
        })
    return out


def _actor_for(db: Session, row: ApprovalToken, decided_by_email: Optional[str]) -> awards.Actor:
    """A known org member by email becomes the actor as themselves; anyone
    else is recorded as the approval link with whatever email they gave."""
    email = (decided_by_email or "").strip().lower()
    if email:
        user = users_repo.get_by_email(db, email)
        if user is not None and user.organization_id == row.organization_id:
            return awards.Actor.from_user(user)
    org = organizations_repo.get_organization(db, row.organization_id)
    return awards.Actor(
        id=f"approval-link:{row.id}",
        email=email or "approval-link",
        company=org.name if org is not None else "",
    )


def execute(db: Session, token: str, *, decided_by_email: Optional[str] = None) -> dict:
    """Approve the award the token carries. 404 unknown token, 410 used or
    expired; otherwise the AwardResult payload (with `poNumbers`) plus
    projectId / packageLabel / decidedByEmail. Marks the token used only once
    the award committed, so a 409 (already awarded, in progress) leaves the
    link live for a retry."""
    row = _load(db, token)
    status = row.status()
    if status == "used":
        raise HTTPException(status_code=410, detail="This award was already approved")
    if status == "expired":
        raise HTTPException(status_code=410, detail="This approval link has expired")
    payload = AwardRequest(**row.award_request())
    actor = _actor_for(db, row, decided_by_email)
    result = awards.award_package(
        db, row.organization_id, row.project_id, row.package, payload, actor
    )
    tokens_repo.mark_used(db, row, decided_by_email)
    result.update({
        "projectId": row.project_id,
        "packageLabel": row.package_label,
        "decidedByEmail": row.decided_by_email,
    })
    return result
