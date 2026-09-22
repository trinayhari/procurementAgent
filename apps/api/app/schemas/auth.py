from typing import Any, Dict, List, Optional

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
    mail you trigger; `null` clears it. It is never a From address: everything
    is sent from the organization's agent inbox (see services/rfq/sender.py)."""

    ccEmail: Optional[EmailStr] = None


class TokenResponse(BaseModel):
    accessToken: str
    tokenType: str = "bearer"
    user: User


class EmailConfig(BaseModel):
    """Effective outbound-email configuration for this organization.

    Lets the UI state the truth instead of implying mail is going out: when
    `configured` is false nothing is delivered, and `inboxAddress` is null
    until the org's agent inbox has been created (first send).
    """

    configured: bool  # PROCUREAI_AGENTMAIL_API_KEY present → real sends
    mocked: bool  # not configured → sends are logged, never delivered
    inboxAddress: Optional[str] = None  # the org's agent inbox (acme@proq.tryproq.dev)
    fromHeader: str  # how your outgoing mail's From: will read
    ccEmail: Optional[EmailStr] = None  # your Cc address, if set
    # Which PROCUREAI_AGENTMAIL_* variables are still unset (empty when configured).
    missing: List[str] = []
    # Last real outcome of talking to AgentMail: {lastError, lastErrorAt, lastOkAt}.
    # `configured` says the key is set; this says the API answered.
    agentmail: Dict[str, Any] = {}
    # The LLM used for quote parsing / RFQ drafting: {configured, model,
    # baseUrl, lastError, lastErrorAt, lastErrorWhere, lastOkAt}. When
    # `lastError` is set replies are parsed by the regex fallback.
    llm: Dict[str, Any] = {}


class TestEmailResult(BaseModel):
    """Outcome of POST /api/auth/test-email (config verification)."""

    mocked: bool  # True → no AgentMail key configured; the "send" was only logged
    messageId: str
    fromAddr: str  # the From identity used (the org's agent inbox + your display name)
    to: str
    cc: Optional[str] = None  # your Cc address, when it isn't already the To
