"""Request/response shapes for the team + invite endpoints."""
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import User


class InviteCreateRequest(BaseModel):
    email: EmailStr


class Invite(BaseModel):
    """A pending/accepted/revoked invitation (never exposes the token)."""

    id: str
    email: EmailStr
    status: str
    invitedByUserId: str
    createdAt: Optional[str] = None
    expiresAt: Optional[str] = None
    acceptedAt: Optional[str] = None
    # Whether the invitation email was actually delivered (a configured
    # provider accepted it). With no email provider configured the "send"
    # is a logging mock — so the accept link is returned instead, for the
    # inviter to pass on by hand. Never set when real email is configured.
    emailed: bool = True
    emailedAt: Optional[str] = None
    # Why the (configured) provider could not deliver it, when `emailed` is
    # false despite email being set up — so the inviter can act on it.
    emailError: Optional[str] = None
    # The accept link, exposed only when the invitation was NOT emailed (no
    # provider, or the send failed) so the inviter can pass it on by hand.
    acceptUrl: Optional[str] = None


class InvitePreview(BaseModel):
    """What the public accept screen shows before the invitee commits: which org
    they're joining and at which email. `valid` is false for a revoked, accepted,
    expired, or unknown token."""

    valid: bool
    organizationName: Optional[str] = None
    email: Optional[EmailStr] = None
    reason: Optional[str] = None  # why it's invalid (expired / revoked / used / unknown)


class AcceptInviteRequest(BaseModel):
    name: str = ""
    password: str = Field(min_length=8, max_length=128)


class TeamMembers(BaseModel):
    members: List[User]
    invites: List[Invite]
