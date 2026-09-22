"""ORM model for an email the platform mailbox received.

Resend Inbound posts every message delivered to <anything>@email_inbound_domain
to POST /api/webhooks/resend; the route stores it here BEFORE any processing,
so nothing is lost if classification or extraction fails (the row can be
re-run). This table is the RFQ inbox: quote ingest and the RFQ conversation
view read supplier replies from here, and the intake flow reads customer
requests from here. Nothing reads a remote mailbox any more.

Attribution:
  * `kind` = "rfq_reply" when the To address is rfq+<rfq_id>@domain (the
    Reply-To every outbound RFQ carries) or In-Reply-To matches a message we
    sent; `rfq_id` is then set.
  * `kind` = "intake" when a known user (User.email) writes to the intake
    address; `organization_id` is that user's org.
  * `kind` = "unknown" otherwise (kept for a human to look at).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InboundEmail(Base):
    __tablename__ = "inbound_emails"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid hex
    # Null until attributed: an RFQ reply inherits the RFQ's org, an intake
    # message the sender's org. Unattributed rows are never shown to a tenant.
    organization_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=True
    )
    # Resend's id for the received email (idempotency key for the webhook).
    provider_message_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    # RFC 2822 headers, for threading.
    rfc_message_id: Mapped[str] = mapped_column(String, index=True, nullable=False, default="")
    in_reply_to: Mapped[str] = mapped_column(String, index=True, nullable=False, default="")
    references: Mapped[str] = mapped_column(Text, nullable=False, default="")
    from_email: Mapped[str] = mapped_column(String, index=True, nullable=False, default="")
    from_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    to_addresses: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    cc_addresses: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    subject: Mapped[str] = mapped_column(String, nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON list of {"filename", "mimeType", "size", "locator"}; the bytes live
    # in object storage (services/storage.py), never in the row.
    attachments: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    # Attribution (see module docstring).
    kind: Mapped[str] = mapped_column(String, index=True, nullable=False, default="unknown")
    rfq_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    # Set once the downstream handler (quote ingest / intake) has consumed the
    # row; `error` holds the last failure so the row can be retried.
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
