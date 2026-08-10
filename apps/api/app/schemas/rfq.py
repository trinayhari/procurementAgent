from typing import List, Literal, Optional

from pydantic import BaseModel, Field

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
    thread: List[ConversationMessage]


class RfqGenerateRequest(BaseModel):
    supplier_ids: List[str]
    # Scope-of-work text for a subcontractor bid request (trade-scope packages
    # only). When set it is also persisted back onto the trade scope document.
    scope: Optional[str] = Field(default=None, max_length=20_000)


class RfqUpdate(BaseModel):
    subject: str
    body: str
    recipients: List[RfqRecipient]
    # Document ids to attach to the outgoing email. None = leave unchanged
    # (an older client that doesn't send the field won't clear attachments).
    attachment_ids: Optional[List[str]] = None
