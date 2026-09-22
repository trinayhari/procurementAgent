"""Received email for the current organization (the agent inbox's mail).

Read-only listing for the dashboard, plus a re-run for a row whose processing
failed or that arrived before its RFQ existed. Mounted in main.py's authed
loop; every read is scoped to the caller's organization.
"""
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.user import User
from app.repositories import inbound_emails as inbound_repo
from app.schemas.inbound import InboundEmailOut

router = APIRouter(prefix="/api/inbound", tags=["inbound"])


@router.get("", response_model=List[InboundEmailOut])
def list_inbound(
    kind: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Received emails, newest first. `kind` filters on the attribution:
    rfq_reply, intake or unknown (mail nobody claimed, for a human to look at)."""
    rows = inbound_repo.list_for_org(db, current_user.organization_id, kind=kind, limit=max(1, min(limit, 500)))
    return [inbound_repo.to_dict(r) for r in rows]


@router.post("/{row_id}/reprocess", response_model=InboundEmailOut)
def reprocess(
    row_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run attribution and handling again for one received email (after a
    failure, or once the RFQ it answers has been sent)."""
    from app.api.routes.webhooks_agentmail import _process

    row = inbound_repo.get(db, current_user.organization_id, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Received email not found")
    inbound_repo.reset_for_reprocess(db, row)
    background.add_task(_process, row.id)
    return inbound_repo.to_dict(row)
