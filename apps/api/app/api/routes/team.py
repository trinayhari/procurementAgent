"""Team + invite endpoints.

Two routers with different gating:
- `router` (/api/team) is added to main's authed group: only a signed-in member
  manages their own org's team (list members, invite, revoke).
- `public_router` (/api/invite) is genuinely public: an invitee previews and
  accepts by token, with no account yet. Accepting creates their user IN THE
  INVITING ORG and logs them in.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import create_access_token, get_current_user
from app.db import get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import organization_invites as invites_repo
from app.repositories import organizations as organizations_repo
from app.repositories import users as users_repo
from app.schemas.auth import TokenResponse
from app.schemas.team import (
    AcceptInviteRequest,
    Invite,
    InviteCreateRequest,
    InvitePreview,
    TeamMembers,
)
from app.services.rfq import sender as rfq_sender

router = APIRouter(prefix="/api/team", tags=["team"])
public_router = APIRouter(prefix="/api/invite", tags=["team"])

# Public accept/preview are unauthenticated and token-guessing-adjacent — keep
# them slow. Inviting is authenticated but still worth a ceiling.
_accept_limit = rate_limit("invite-accept", limit=10, window_s=60)
_preview_limit = rate_limit("invite-preview", limit=30, window_s=60)
_invite_limit = rate_limit("invite-create", limit=20, window_s=60)


def _accept_url(token: str) -> str:
    """The invitee-facing accept link embedded in the invitation email."""
    base = settings.app_base_url or (settings.cors_origins[0] if settings.cors_origins else "")
    base = base.rstrip("/")
    return f"{base}/#/invite/{token}" if base else f"/#/invite/{token}"


# --------------------------------------------------------------------------- #
# Authenticated team management (scoped to the caller's organization).
# --------------------------------------------------------------------------- #

@router.get("", response_model=TeamMembers)
def get_team(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The org's roster: current members plus still-open invitations."""
    org_id = current_user.organization_id
    members = [u.to_dict() for u in users_repo.list_for_org(db, org_id)]
    invites = [i.to_dict() for i in invites_repo.list_pending(db, org_id)]
    return {"members": members, "invites": invites}


@router.post(
    "/invites",
    response_model=Invite,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_invite_limit)],
)
def create_invite(
    body: InviteCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invite a teammate by email to join the caller's organization."""
    org_id = current_user.organization_id
    email = body.email.strip().lower()

    # Email is globally unique, so anyone with an account (in ANY org) can't
    # accept — reject up front rather than mint a dead invite.
    if users_repo.get_by_email(db, email) is not None:
        raise HTTPException(status_code=409, detail="That email already has a Proq account.")
    # Don't stack duplicate live invites for the same person.
    if invites_repo.get_pending_for_email(db, org_id, email) is not None:
        raise HTTPException(status_code=409, detail="An invite for that email is already pending.")

    invite = invites_repo.create_invite(db, org_id, email, invited_by_user_id=current_user.id)
    org = organizations_repo.get_organization(db, org_id)
    org_name = org.name if org is not None else "your team"

    # Best-effort email (mocked when Gmail isn't configured). A send failure must
    # not fail the invite — the row exists and can be re-sent.
    try:
        sender = rfq_sender.get_sender()
        sender.send(
            email,
            f"You're invited to join {org_name} on Proq",
            (
                f"{current_user.name or current_user.email} invited you to join "
                f"{org_name} on Proq.\n\nAccept your invitation:\n{_accept_url(invite.token)}\n\n"
                "This link expires in 7 days.\n\n— Proq"
            ),
            from_addr=rfq_sender.sender_address(),
        )
    except Exception:
        pass

    audit_repo.log(
        db, org_id, current_user, "team.invited", "organization_invite", invite.id,
        detail={"email": email},
    )
    return invite.to_dict()


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(
    invite_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a pending invitation. 404 for an unknown id or another org's."""
    org_id = current_user.organization_id
    invite = invites_repo.revoke(db, org_id, invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    audit_repo.log(
        db, org_id, current_user, "team.invite_revoked", "organization_invite", invite_id,
        detail={"email": invite.email},
    )
    return None


# --------------------------------------------------------------------------- #
# Public invite acceptance (no auth — the invitee has no account yet).
# --------------------------------------------------------------------------- #

@public_router.get("/{token}", response_model=InvitePreview, dependencies=[Depends(_preview_limit)])
def preview_invite(token: str, db: Session = Depends(get_db)):
    """What the accept screen shows before the invitee commits. Never reveals
    whether a token is real beyond valid/invalid + a coarse reason."""
    invite = invites_repo.get_by_token(db, token)
    if invite is None:
        return {"valid": False, "reason": "unknown"}
    if invite.status == "accepted":
        return {"valid": False, "reason": "used"}
    if invite.status == "revoked":
        return {"valid": False, "reason": "revoked"}
    if not invite.is_live():
        return {"valid": False, "reason": "expired"}
    org = organizations_repo.get_organization(db, invite.organization_id)
    return {
        "valid": True,
        "organizationName": org.name if org is not None else None,
        "email": invite.email,
    }


@public_router.post(
    "/{token}/accept",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_accept_limit)],
)
def accept_invite(token: str, body: AcceptInviteRequest, db: Session = Depends(get_db)):
    """Redeem an invite: create the user in the inviting org and log them in.

    The email is taken from the invite (the invitee can't change who was
    invited); only name + password come from the request."""
    invite = invites_repo.get_by_token(db, token)
    if invite is None or not invite.is_live():
        raise HTTPException(status_code=400, detail="This invitation is no longer valid.")
    # Race: someone registered this email between invite and accept.
    if users_repo.get_by_email(db, invite.email) is not None:
        raise HTTPException(status_code=409, detail="That email already has a Proq account.")

    user = users_repo.create_user(
        db, invite.organization_id, email=invite.email, password=body.password, name=body.name
    )
    invites_repo.mark_accepted(db, invite)
    audit_repo.log(
        db, invite.organization_id, user, "team.invite_accepted", "user", user.id,
        detail={"invite": invite.id},
    )
    access = create_access_token(user.id)
    return {"accessToken": access, "tokenType": "bearer", "user": user.to_dict()}
