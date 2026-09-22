"""Supplier replies to RFQs (owned by the Resend transport work).

attribute(): set msg.rfq_id / organization_id / project_id when the message
is a reply to one of our RFQs. Return True when it is.
handle(): parse the quote (services/quotes) and mark the row processed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.inbound_email import InboundEmail


def attribute(db: Session, msg: InboundEmail) -> bool:
    raise NotImplementedError


def handle(db: Session, msg: InboundEmail) -> None:
    raise NotImplementedError
