"""Database accessors for received emails (the agent inboxes' mail).

Rows are written by the AgentMail webhook before any processing and consumed
by services/inbound. Every tenant-facing read filters on organization_id.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.inbound_email import InboundEmail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_by_provider_id(db: Session, provider_message_id: str) -> Optional[InboundEmail]:
    if not provider_message_id:
        return None
    return db.scalars(
        select(InboundEmail).where(InboundEmail.provider_message_id == provider_message_id)
    ).first()


def get(db: Session, org_id: str, row_id: str) -> Optional[InboundEmail]:
    """The row, or None when it doesn't exist *or* belongs to another org."""
    row = db.get(InboundEmail, row_id)
    return row if row is not None and row.organization_id == org_id else None


def create(db: Session, **fields) -> InboundEmail:
    """Insert a received email. Address lists and attachments are stored as
    JSON text; pass Python lists."""
    for key in ("to_addresses", "cc_addresses", "attachments"):
        value = fields.get(key)
        if not isinstance(value, str):
            fields[key] = json.dumps(value or [])
    row = InboundEmail(id=fields.pop("id", None) or uuid.uuid4().hex, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_for_org(db: Session, org_id: str, kind: Optional[str] = None,
                 limit: int = 100) -> List[InboundEmail]:
    stmt = select(InboundEmail).where(InboundEmail.organization_id == org_id)
    if kind:
        stmt = stmt.where(InboundEmail.kind == kind)
    stmt = stmt.order_by(InboundEmail.received_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def list_for_rfq(db: Session, org_id: str, rfq_id: str) -> List[InboundEmail]:
    """Supplier replies attributed to an RFQ, oldest first (the conversation view)."""
    return list(db.scalars(
        select(InboundEmail)
        .where(InboundEmail.organization_id == org_id, InboundEmail.rfq_id == rfq_id)
        .order_by(InboundEmail.received_at.asc())
    ).all())


def list_unprocessed_for_project(db: Session, org_id: str, project_id: str) -> List[InboundEmail]:
    """RFQ replies on a project not yet turned into quotes, oldest first."""
    return list(db.scalars(
        select(InboundEmail)
        .where(
            InboundEmail.organization_id == org_id,
            InboundEmail.project_id == project_id,
            InboundEmail.kind == "rfq_reply",
            InboundEmail.processed_at.is_(None),
        )
        .order_by(InboundEmail.received_at.asc())
    ).all())


def count_for_project(db: Session, org_id: str, project_id: str) -> int:
    """How many RFQ replies (processed or not) a project has received."""
    return len(db.scalars(
        select(InboundEmail.id).where(
            InboundEmail.organization_id == org_id,
            InboundEmail.project_id == project_id,
            InboundEmail.kind == "rfq_reply",
        )
    ).all())


def mark_processed(db: Session, row: InboundEmail) -> None:
    row.processed_at = _utcnow()
    row.error = None
    db.add(row)
    db.commit()


def mark_failed(db: Session, row: InboundEmail, error: str) -> None:
    row.attempts = (row.attempts or 0) + 1
    row.error = (error or "")[:2000]
    db.add(row)
    db.commit()


def reset_for_reprocess(db: Session, row: InboundEmail) -> None:
    """Clear processing state and attribution so handle() runs again."""
    row.processed_at = None
    row.error = None
    row.kind = "unknown"
    row.rfq_id = None
    row.project_id = None
    db.add(row)
    db.commit()


def to_dict(row: InboundEmail) -> dict:
    def _list(text: str) -> list:
        try:
            return json.loads(text or "[]")
        except ValueError:
            return []

    return {
        "id": row.id,
        "organizationId": row.organization_id,
        "providerMessageId": row.provider_message_id,
        "inboxId": row.inbox_id,
        "threadId": row.thread_id,
        "inReplyTo": row.in_reply_to,
        "fromEmail": row.from_email,
        "fromName": row.from_name,
        "to": _list(row.to_addresses),
        "cc": _list(row.cc_addresses),
        "subject": row.subject,
        "text": row.text,
        "attachments": _list(row.attachments),
        "receivedAt": row.received_at.isoformat() if row.received_at else None,
        "kind": row.kind,
        "rfqId": row.rfq_id,
        "projectId": row.project_id,
        "processedAt": row.processed_at.isoformat() if row.processed_at else None,
        "error": row.error,
        "attempts": row.attempts,
    }
