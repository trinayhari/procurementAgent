from fastapi import APIRouter, HTTPException

from app.repositories import seed
from app.schemas.rfq import FollowupDraft, MessageCreate, RfqDetail, ThreadMessage

router = APIRouter(prefix="/api/rfqs", tags=["rfqs"])


@router.get("/{rfq_id}", response_model=RfqDetail)
def get_rfq(rfq_id: str):
    rfq = seed.get_rfq(rfq_id)
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return {**rfq, "thread": seed._thread_for(rfq)}


@router.post("/{rfq_id}/messages", response_model=ThreadMessage)
def send_message(rfq_id: str, payload: MessageCreate):
    """Command: post a reply to an RFQ thread."""
    rfq = seed.get_rfq(rfq_id)
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return {
        "dir": "out",
        "who": "You · ProcureAI",
        "initials": "JM",
        "time": "Just now",
        "body": payload.body,
    }


@router.post("/{rfq_id}/followup", response_model=FollowupDraft)
def draft_followup(rfq_id: str):
    """Command: generate an AI follow-up nudge for a non-responsive supplier.

    Stubbed — returns a templated message. Replace with an LLM call.
    """
    rfq = seed.get_rfq(rfq_id)
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    first_name = rfq["sup"].split(" ")[0]
    return {
        "body": (
            "Hi {name}, checking in on our {pkg} RFQ — any update on timing?".format(
                name=first_name, pkg=rfq["pkg"]
            )
        )
    }
