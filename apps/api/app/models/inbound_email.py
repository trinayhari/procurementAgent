"""ORM model for an email one of the agent inboxes received.

AgentMail posts every message that arrives in any of our inboxes to
POST /api/webhooks/agentmail; the route stores it here BEFORE any processing,
so nothing is lost if classification or extraction fails (the row can be
re-run). Quote ingest and the intake flow consume rows from here; the message
body and thread also stay in AgentMail (thread_id) for the conversation view.

Attribution (see services/inbound):
  * `organization_id` comes from `inbox_id`: each org owns one agent inbox.
  * `kind` = "rfq_reply" when `thread_id` matches a thread an RFQ was sent
    in (or In-Reply-To matches a message we sent); `rfq_id` is then set.
  * `kind` = "intake" when the sender is a known user of that org.
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
    # AgentMail message id (idempotency key for the webhook) and the inbox
    # and thread it belongs to.
    provider_message_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    inbox_id: Mapped[str] = mapped_column(String, index=True, nullable=False, default="")
    thread_id: Mapped[str] = mapped_column(String, index=True, nullable=False, default="")
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
