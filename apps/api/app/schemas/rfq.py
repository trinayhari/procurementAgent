import re
from typing import Any, Dict, List, Literal, Optional

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


# ------------------------------------------------ persisted (generated) RFQs
class RfqFollowup(BaseModel):
    """One nudge to a recipient. `messageId` is null while the send is in
    flight (an intent); see services/rfq/followups.py."""

    n: int
    sentAt: str
    messageId: Optional[str] = None


class RfqRecipient(BaseModel):
    supplierId: Optional[str] = None
    name: str
    email: str
    # AgentMail id of the RFQ message we sent (`sentMessageId` is the same id
    # under its older name) and the thread it created: a supplier reply in
    # that thread is attributed to this RFQ.
    messageId: Optional[str] = None
    sentMessageId: Optional[str] = None
    threadId: Optional[str] = None
    sentAt: Optional[str] = None  # ISO UTC time of the successful send
    repliedAt: Optional[str] = None  # ISO UTC time of the first supplier reply
    sendStatus: Optional[str] = None  # "sent" | "failed" | None (not yet attempted)
    sendError: Optional[str] = None  # human-readable failure reason when sendStatus="failed"
    # Ids of later messages we sent this recipient on the RFQ thread (award /
    # decline notices); a reply to one of them still attributes here.
    outboundMessageIds: Optional[List[str]] = None
    # Follow-up nudges sent by the scheduler: [{sentAt, messageId}].
    followups: Optional[List[Dict[str, Any]]] = None
    # True when the "send" went through the logging mock (no AgentMail key):
    # recorded as sent for workflow purposes, but nothing was delivered.
    mock: Optional[bool] = None
    # Written by the follow-up engine (services/rfq/followups.py) and the
    # inbound reply path: when this supplier answered, and each nudge we sent.
    repliedAt: Optional[str] = None
    followups: Optional[List[RfqFollowup]] = None


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
    # True when the thread includes replies the agent inbox received; False
    # when it is the stored RFQ plus ingested quotes rendered as replies.
    live: bool
    # Whether AgentMail is configured at all (False → mock sends, no replies).
    configured: bool = False
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


# ------------------------------------------------------------- follow-ups
class RecipientFollowupStatus(BaseModel):
    """Per-recipient chase state for GET .../rfqs/{rfq_id}/followups."""

    email: str
    supplierName: str = ""
    sentAt: Optional[str] = None
    repliedAt: Optional[str] = None
    replied: bool = False
    followups: List[RfqFollowup] = []
    # When the next automatic nudge becomes due; null when exhausted, replied,
    # or the package is already awarded.
    nextDueAt: Optional[str] = None


class RfqFollowupStatus(BaseModel):
    rfqId: str
    max: int
    recipients: List[RecipientFollowupStatus]


class FollowupRunResult(BaseModel):
    """Outcome of POST .../followups/run (the manual "chase now")."""

    rfqsScanned: int
    nudgesSent: int
    skippedOutsideHours: int
    errors: List[str] = []
    recipients: List[RecipientFollowupStatus]
