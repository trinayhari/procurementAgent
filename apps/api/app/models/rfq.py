import json
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Rfq(Base):
    """A per-package RFQ draft (and, once sent, its delivery record)."""

    __tablename__ = "rfqs"

    # Tenant boundary — every read/write filters on this explicitly.
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), index=True, nullable=False
    )
    package: Mapped[str] = mapped_column(String, nullable=False)  # category key
    package_label: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="Draft")
    subject: Mapped[str] = mapped_column(String, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    line_items: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    recipients: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    # "materials" (BOM-driven quote request) or "subcontractor" (scope-of-work
    # bid request). Set by the server at generate time — never inferred from the
    # package key, which may point at a since-deleted document.
    kind: Mapped[str] = mapped_column(String, nullable=False, default="materials")
    # JSON list of {"documentId", "name"} — project documents the user chose to
    # attach to the outgoing email. Stored denormalized like `recipients`.
    attachments: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    _STATUS_TONE = {
        "Draft": "gray",
        "Sent": "blue",
        "Awaiting": "warn",
        "Send failed": "danger",
        "Quoted": "success",
    }

    def to_dict(self) -> dict:
        recipients = json.loads(self.recipients or "[]")
        first = recipients[0]["name"] if recipients else "—"
        more = f" +{len(recipients) - 1} more" if len(recipients) > 1 else ""
        return {
            "id": self.id,
            "projectId": self.project_id,
            "package": self.package,
            # Fields the existing RFQ list UI expects:
            "sup": (first + more) if recipients else "No recipients",
            "pkg": self.package_label or self.package,
            "folder": self.status,
            "status": self.status,
            "statusTone": self._STATUS_TONE.get(self.status, "gray"),
            "preview": (self.body or "").strip().split("\n")[0][:80] or "Draft RFQ",
            "time": "—",
            "unread": False,
            "logo": "RF",
            "logoBg": "#334155",
            # Detail fields:
            "subject": self.subject,
            "body": self.body,
            "lineItems": json.loads(self.line_items or "[]"),
            "recipients": recipients,
            "kind": self.kind or "materials",
            "attachments": json.loads(self.attachments or "[]"),
        }
