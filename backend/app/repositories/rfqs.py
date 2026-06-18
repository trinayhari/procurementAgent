"""Database accessors for persisted RFQs."""
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rfq import Rfq


def create_rfq_draft(
    db: Session,
    project_id: str,
    package: str,
    package_label: str,
    subject: str,
    body: str,
    line_items: List[dict],
    recipients: List[dict],
) -> dict:
    row = Rfq(
        id=uuid.uuid4().hex,
        project_id=project_id,
        package=package,
        package_label=package_label,
        status="Draft",
        subject=subject,
        body=body,
        line_items=json.dumps(line_items),
        recipients=json.dumps(recipients),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


def get_rfq(db: Session, rfq_id: str) -> Optional[dict]:
    row = db.get(Rfq, rfq_id)
    return row.to_dict() if row else None


def list_rfqs(db: Session, project_id: str) -> List[dict]:
    rows = db.scalars(
        select(Rfq).where(Rfq.project_id == project_id).order_by(Rfq.created_at.desc())
    ).all()
    return [r.to_dict() for r in rows]


def update_rfq(
    db: Session,
    rfq_id: str,
    subject: str,
    body: str,
    recipients: List[dict],
) -> Optional[dict]:
    row = db.get(Rfq, rfq_id)
    if row is None:
        return None
    row.subject = subject
    row.body = body
    row.recipients = json.dumps(recipients)
    db.commit()
    db.refresh(row)
    return row.to_dict()


def mark_rfq_sent(db: Session, rfq_id: str, recipients: List[dict]) -> Optional[dict]:
    """Persist send results (recipients now carry sentMessageId) and flip status."""
    row = db.get(Rfq, rfq_id)
    if row is None:
        return None
    row.recipients = json.dumps(recipients)
    row.status = "Sent"
    row.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row.to_dict()
