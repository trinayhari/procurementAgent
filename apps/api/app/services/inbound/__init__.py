"""Inbound email dispatch.

POST /api/webhooks/resend stores each received email as an InboundEmail row,
then calls `handle(db, row)`. Attribution decides who owns the message:

  * an RFQ reply (To = rfq+<rfq_id>@domain, or In-Reply-To one of ours)
    goes to `rfq_replies.handle`: quote parsing + the RFQ conversation;
  * a message from a known user goes to `intake.handle`: the customer is
    asking the agent to run a buy (new plan set, addendum, question);
  * anything else stays `kind="unknown"` for a human to look at.

Handlers are idempotent on `processed_at` and record failures in `error`
so a row can be re-run from the API.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.inbound_email import InboundEmail

logger = logging.getLogger("procureai.inbound")


def handle(db: Session, msg: InboundEmail) -> None:
    from app.services.inbound import intake, rfq_replies

    if msg.processed_at is not None:
        return
    if msg.kind == "unknown":
        # Attribution runs once, cheapest signal first.
        if rfq_replies.attribute(db, msg):
            msg.kind = "rfq_reply"
        elif intake.attribute(db, msg):
            msg.kind = "intake"
        db.add(msg)
        db.commit()
    if msg.kind == "rfq_reply":
        rfq_replies.handle(db, msg)
    elif msg.kind == "intake":
        intake.handle(db, msg)
    else:
        logger.info("inbound %s from %s left unattributed", msg.id, msg.from_email)
