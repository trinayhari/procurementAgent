"""Email channel: a notice becomes a plain-text reply in the customer's thread.

Where the reply goes, in order:
  1. `Notice.thread` with channel "email": reply to that message (In-Reply-To
     = its Message-ID, To = its sender, Subject = "Re: " + its subject).
  2. The latest intake email for the project (`inbound_emails` rows with
     kind="intake"): the customer who sent the plan set gets the progress
     report back in the same thread they started (In-Reply-To = the row's
     provider message id, else its RFC Message-ID).
  3. The organization's first user (by seq), as a fresh email.
No user at all → the notice is skipped with a log line, never raised.

Sends go through the shared EmailSender (services/rfq/sender.py) for the
org's agent inbox, so with no provider configured they hit MockSender and
only log.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.inbound_email import InboundEmail
from app.repositories import users as users_repo
from app.services.notify import Notice, ThreadRef
# Bound at import (not looked up on the module per call) so a test that swaps
# the RFQ sender to count supplier mail does not also count these status
# notices; tests of this channel patch `email.get_sender` instead.
from app.services.rfq.sender import from_header, get_sender

logger = logging.getLogger("procureai.notify.email")


def _sender(db: Session, org_id: str):
    """The org's EmailSender (its AgentMail agent inbox, or the mock)."""
    return get_sender(db, org_id)

SIGN_OFF = "Proq"


def render(notice: Notice) -> str:
    """Title, the lines as bullets, then one "<label>: <url>" per action."""
    parts = [notice.title]
    if notice.lines:
        parts.append("\n".join(f"- {line}" for line in notice.lines))
    if notice.actions:
        parts.append("\n".join(f"{a.label}: {a.url}" for a in notice.actions))
    parts.append(SIGN_OFF)
    return "\n\n".join(parts)


def _reply_subject(subject: str) -> str:
    subject = (subject or "").strip()
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}" if subject else ""


def latest_intake(db: Session, org_id: str, project_id: str) -> Optional[InboundEmail]:
    """The most recent customer email attached to this project, if any."""
    return db.scalars(
        select(InboundEmail)
        .where(
            InboundEmail.organization_id == org_id,
            InboundEmail.project_id == project_id,
            InboundEmail.kind == "intake",
        )
        .order_by(InboundEmail.received_at.desc(), InboundEmail.id.desc())
    ).first()


def resolve_recipient(db: Session, notice: Notice) -> Tuple[str, Optional[str], str]:
    """(to, in_reply_to, subject) for a notice; `to` is "" when nobody can be addressed."""
    thread: Optional[ThreadRef] = notice.thread
    if thread is not None and thread.channel == "email" and thread.email_address:
        subject = _reply_subject(thread.email_subject) or notice.title
        return thread.email_address, thread.email_message_id or None, subject
    if notice.project_id:
        intake = latest_intake(db, notice.org_id, notice.project_id)
        if intake is not None and intake.from_email:
            subject = _reply_subject(intake.subject) or notice.title
            # The provider's id is what threads a reply on AgentMail; the RFC
            # Message-ID is the fallback for rows that only carry headers.
            reply_to_id = intake.provider_message_id or intake.rfc_message_id or None
            return intake.from_email, reply_to_id, subject
    users = users_repo.list_for_org(db, notice.org_id)
    if users:
        return users[0].email, None, notice.title
    return "", None, notice.title


class EmailNotifier:
    name = "email"

    def notify(self, db: Session, notice: Notice) -> None:
        to, in_reply_to, subject = resolve_recipient(db, notice)
        if not to:
            logger.info("notice %s for org %s skipped: no user to email", notice.kind, notice.org_id)
            return
        sender = _sender(db, notice.org_id)
        sent = sender.send(
            to, subject, render(notice),
            from_addr=from_header(None), in_reply_to=in_reply_to,
        )
        logger.info(
            "notice %s emailed to %s (reply=%s, id=%s)",
            notice.kind, to, bool(in_reply_to), getattr(sent, "message_id", ""),
        )
