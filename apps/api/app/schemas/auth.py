from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = ""
    company: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class User(BaseModel):
    """Public-safe user shape (never includes the password hash)."""

    id: str
    email: EmailStr
    name: str
    company: str
    # The tenant this user belongs to; everything the account can see is scoped
    # to it.
    organizationId: str
    ccEmail: Optional[EmailStr] = None
    createdAt: Optional[str] = None


class UpdateMeRequest(BaseModel):
    """Editable account settings. `ccEmail` is the address copied on outgoing
    mail you trigger; `null` clears it. It is never a From address — everything
    is sent from the workspace mailbox (see services/rfq/sender.py)."""

    ccEmail: Optional[EmailStr] = None


class TokenResponse(BaseModel):
    accessToken: str
    tokenType: str = "bearer"
    user: User


class EmailConfig(BaseModel):
    """Effective outbound-email configuration, straight from the environment.

    Lets the UI state the truth instead of implying mail is going out: when
    `configured` is false nothing is delivered, and when `senderAddressSet` is
    false `fromAddress` is only a placeholder.
    """

    configured: bool  # all three PROCUREAI_GMAIL_* OAuth vars present
    mocked: bool  # not configured → sends are logged, never delivered
    senderAddressSet: bool  # PROCUREAI_GMAIL_SENDER_ADDRESS is set
    fromAddress: str  # the workspace mailbox every email is sent from
    fromHeader: str  # how your outgoing mail's From: will read
    ccEmail: Optional[EmailStr] = None  # your Cc address, if set


class TestEmailResult(BaseModel):
    """Outcome of POST /api/auth/test-email (config verification)."""

    mocked: bool  # True → no Gmail configured; the "send" was only logged
    messageId: str
    fromAddr: str  # the From header used (workspace mailbox + your display name)
    to: str
    cc: Optional[str] = None  # your Cc address, when it isn't already the To
