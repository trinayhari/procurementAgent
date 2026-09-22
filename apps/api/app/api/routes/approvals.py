"""Public approval links (single-use tokens): GET previews the decision, POST
executes it. Mounted without auth in main.py: the approver may have no
account, the token in the link is the credential. Rate-limited like the
invite preview because the routes are unauthenticated and token-guessing
adjacent. The work lives in services/approvals.py so the Slack button can
run the same code in-process."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.ratelimit import rate_limit
from app.db import get_db
from app.schemas.approval import ApprovalExecuteRequest, ApprovalPreview, ApprovalResult
from app.services import approvals as approvals_service

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

_preview_limit = rate_limit("approval-preview", limit=30, window_s=60)
_execute_limit = rate_limit("approval-execute", limit=10, window_s=60)


@router.get("/{token}", response_model=ApprovalPreview, dependencies=[Depends(_preview_limit)])
def preview_approval(token: str, db: Session = Depends(get_db)):
    """The award card behind the link: package, winners, totals, and whether
    the link is still pending, already used, or expired. 404 for an unknown token."""
    return approvals_service.preview(db, token)


@router.post("/{token}", response_model=ApprovalResult, dependencies=[Depends(_execute_limit)])
def execute_approval(
    token: str,
    body: Optional[ApprovalExecuteRequest] = None,
    db: Session = Depends(get_db),
):
    """Approve the award: runs the same locked award path as the dashboard,
    issues the POs, marks the token used. 410 when used or expired."""
    email = body.decidedByEmail if body is not None else None
    return approvals_service.execute(db, token, decided_by_email=email)
