from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories import reference as reference_repo
from app.schemas.rfq import FollowupDraft, MessageCreate, RfqDetail, ThreadMessage

router = APIRouter(prefix="/api/rfqs", tags=["rfqs"])

# These endpoints serve ONLY the prototype's demo RFQ inbox (`demo_rfqs`), which
# is global seed data identical for every organization — so there is nothing
# tenant-specific here to scope. Real, generated RFQs live under
# /api/projects/{project_id}/rfqs/{rfq_id} and are org-filtered there.


@router.get("/{rfq_id}", response_model=RfqDetail)
def get_rfq(rfq_id: str, db: Session = Depends(get_db)):
    rfq = reference_repo.get_demo_rfq(db, rfq_id)
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return rfq.to_detail()


@router.post("/{rfq_id}/messages", response_model=ThreadMessage)
def send_message(rfq_id: str, payload: MessageCreate, db: Session = Depends(get_db)):
    """Command: post a reply to an RFQ thread."""
    rfq = reference_repo.get_demo_rfq(db, rfq_id)
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return {
        "dir": "out",
        "who": "You · Proq",
        "initials": "JM",
        "time": "Just now",
        "body": payload.body,
    }


@router.post("/{rfq_id}/followup", response_model=FollowupDraft)
def draft_followup(rfq_id: str, db: Session = Depends(get_db)):
    """Command: generate an AI follow-up nudge for a non-responsive supplier.

    Stubbed — returns a templated message. Replace with an LLM call.
    """
    rfq = reference_repo.get_demo_rfq(db, rfq_id)
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    first_name = rfq.sup.split(" ")[0]
    return {
        "body": (
            "Hi {name}, checking in on our {pkg} RFQ — any update on timing?".format(
                name=first_name, pkg=rfq.pkg
            )
        )
    }
