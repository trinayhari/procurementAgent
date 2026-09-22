"""Adapter between a Slack message and the intake service.

Intake (services/inbound/intake.py) is owned by the email-intake work and
exposes

    handle_request(db, *, org_id, user, text, subject, attachments, thread)
        -> IntakeResult   (has .project_id)

where attachments are `{filename, mimeType, size, locator}` dicts (bytes in
object storage) and thread is a notify.ThreadRef. The import is deferred so
this module loads before intake is merged; until then the customer gets an
honest "stored, not processed yet" reply in the thread.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.notify import ThreadRef

logger = logging.getLogger("procureai.slack")

NOT_WIRED_TEXT = "I stored the file but intake is not wired up yet."


def handle(
    db: Session,
    *,
    org_id: str,
    user: User,
    text: str,
    subject: str,
    attachments: List[dict],
    thread: ThreadRef,
) -> Optional[Any]:
    """Run intake for a Slack request. Returns the IntakeResult, or None when
    intake is not available yet (the caller has already been told)."""
    try:
        from app.services.inbound import intake

        handle_request = intake.handle_request
    except (ImportError, AttributeError):
        logger.warning("slack intake: services.inbound.intake.handle_request is not available")
        return None
    try:
        return handle_request(
            db,
            org_id=org_id,
            user=user,
            text=text,
            subject=subject,
            attachments=attachments,
            thread=thread,
        )
    except NotImplementedError:
        logger.warning("slack intake: handle_request is still a stub")
        return None
