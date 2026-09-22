"""Customer requests sent to the agent by email (owned by the intake work).

attribute(): the sender is a known User → set organization_id. Return True.
handle(): understand the request (new plan set, addendum, question), create
or find the project, store attachments as documents, kick off extraction,
and reply in-thread via services.notify.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.inbound_email import InboundEmail


def attribute(db: Session, msg: InboundEmail) -> bool:
    raise NotImplementedError


def handle(db: Session, msg: InboundEmail) -> None:
    raise NotImplementedError
