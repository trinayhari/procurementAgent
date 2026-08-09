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
