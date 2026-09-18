import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import RfqStatus, Tone


class Rfq(BaseModel):
    id: str
    sup: str
    pkg: str
    folder: str
    status: RfqStatus
    statusTone: Tone
    preview: str
    time: str
    unread: bool = False
    logo: str
    logoBg: str


class RfqFolder(BaseModel):
    name: str
    count: str


class ThreadMessage(BaseModel):
    dir: str  # "in" | "out"
    who: str
    initials: str
    time: str
    body: str
    subject: Optional[str] = None
    attach: Optional[str] = None
    logoBg: Optional[str] = None


class RfqDetail(Rfq):
    thread: List[ThreadMessage]


class MessageCreate(BaseModel):
    body: str


class FollowupDraft(BaseModel):
    body: str


# ------------------------------------------------ persisted (generated) RFQs
class RfqRecipient(BaseModel):
    supplierId: Optional[str] = None
    name: str
    email: str
    sentMessageId: Optional[str] = None
    threadId: Optional[str] = None  # Gmail thread the send landed in (for conversation fetch)
    sendStatus: Optional[str] = None  # "sent" | "failed" | None (not yet attempted)
    sendError: Optional[str] = None  # human-readable failure reason when sendStatus="failed"
    # Gmail ids of later messages we sent this recipient on the RFQ thread
    # (award / decline notices); ingest skips them.
    outboundMessageIds: Optional[List[str]] = None
    # True when the "send" went through the logging mock (no Gmail configured)
    # — recorded as sent for workflow purposes, but nothing was delivered.
    mock: Optional[bool] = None


class RfqLineItem(BaseModel):
    n: str
    q: str = ""


class RfqAttachment(BaseModel):
    """A project document the user chose to attach to the outgoing email."""

    documentId: str
    name: str


class PersistedRfq(Rfq):
    """An RFQ generated from a buy-package, stored per project."""

    projectId: str
    package: str
    subject: str
    body: str
    lineItems: List[RfqLineItem] = []
    recipients: List[RfqRecipient] = []
    # "materials" (BOM quote request) or "subcontractor" (scope-of-work bid).
    kind: Literal["materials", "subcontractor"] = "materials"
    attachments: List[RfqAttachment] = []
    # ISO timestamp of the (last) send; null for drafts.
    sentAt: Optional[str] = None


class ConversationMessage(BaseModel):
    dir: str  # "in" | "out"
    who: str
    initials: str
    time: str
    body: str
    subject: Optional[str] = None
    attach: Optional[str] = None
    logoBg: Optional[str] = None


class RfqConversation(BaseModel):
    """The full email thread for an RFQ, plus its (possibly updated) status."""

    rfqId: str
    status: RfqStatus
    statusTone: Tone
    gmail: bool  # True when messages came from a live Gmail thread
    # Whether Gmail is configured at all (False → the thread is always local).
    configured: bool = False
    # When Gmail is configured but the live read failed, why — the thread
    # below is then the locally stored copy, not the live conversation.
    readError: Optional[str] = None
    thread: List[ConversationMessage]


class RfqGenerateRequest(BaseModel):
    supplier_ids: List[str]
    # Scope-of-work text for a subcontractor bid request (trade-scope packages
    # only). When set it is also persisted back onto the trade scope document.
    scope: Optional[str] = Field(default=None, max_length=20_000)


# Deliberately loose (anything@anything.tld): the point is to catch a recipient
# row that was edited into something Gmail will reject outright, not to
# validate deliverability.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RfqUpdate(BaseModel):
    subject: str
    body: str
    recipients: List[RfqRecipient]

    @field_validator("recipients")
    @classmethod
    def _recipients_have_valid_emails(cls, recipients: List[RfqRecipient]) -> List[RfqRecipient]:
        for r in recipients:
            r.email = (r.email or "").strip()
            if not _EMAIL_RE.match(r.email):
                raise ValueError(
                    f"'{r.email or '(blank)'}' is not a valid email address"
                )
        return recipients
    # Document ids to attach to the outgoing email. None = leave unchanged
    # (an older client that doesn't send the field won't clear attachments).
    # Count-capped: the byte budget alone doesn't bound N tiny files, each of
    # which costs storage round-trips at save and a MIME part per recipient.
    attachment_ids: Optional[List[str]] = Field(default=None, max_length=20)
