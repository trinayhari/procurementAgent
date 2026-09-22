from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class InboundEmailOut(BaseModel):
    """A received email as GET /api/inbound lists it (bodies included; the
    attachment bytes stay in storage, only their descriptors are here)."""

    id: str
    organizationId: Optional[str] = None
    providerMessageId: str
    inboxId: str
    threadId: str
    inReplyTo: str = ""
    fromEmail: str
    fromName: str = ""
    to: List[str] = []
    cc: List[str] = []
    subject: str = ""
    text: str = ""
    # [{filename, mimeType, size, locator}]
    attachments: List[Dict[str, Any]] = []
    receivedAt: Optional[str] = None
    # rfq_reply | intake | unknown
    kind: str
    rfqId: Optional[str] = None
    projectId: Optional[str] = None
    processedAt: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
