from typing import List, Optional

from pydantic import BaseModel

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


class RfqLineItem(BaseModel):
    n: str
    q: str = ""


class PersistedRfq(Rfq):
    """An RFQ generated from a buy-package, stored per project."""

    projectId: str
    package: str
    subject: str
    body: str
    lineItems: List[RfqLineItem] = []
    recipients: List[RfqRecipient] = []


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


class RfqUpdate(BaseModel):
    subject: str
    body: str
    recipients: List[RfqRecipient]


class AdHocRfqGenerateRequest(BaseModel):
    """Generate an ad-hoc RFQ from suppliers found via a free-text search.

    ``description`` is what the user typed they need (drives the subject and is
    the default line item); ``supplier_ids`` are the chosen found-suppliers.
    """

    supplier_ids: List[str]
    description: str
    lineItems: List[RfqLineItem] = []
