from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.user import User
from app.repositories import quotes as quotes_repo
from app.repositories import reference as reference_repo
from app.schemas.quote import SelectResult

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


@router.get("/{quote_id}")
def get_quote(
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    quote = quotes_repo.get_quote(db, current_user.organization_id, quote_id)
    if quote is not None:
        return quote
    # Prototype fallback: the demo quotes are global seed literals, identical
    # for every organization, so serving them here leaks nothing.
    demo_quote = reference_repo.get_demo_quote(db, quote_id)
    if demo_quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return demo_quote


@router.post("/{quote_id}/select", response_model=SelectResult)
def select_quote(
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Command: select a supplier's quote and issue a purchase order."""
    quote = quotes_repo.select_quote(db, current_user.organization_id, quote_id)
    if quote is not None:
        total = f"${quote['total']:,.0f}" if quote.get("total") is not None else "—"
        return {
            "quote_id": quote_id,
            "status": "po_issued",
            "message": "Purchase order issued to {sup} for {pkg} ({total}).".format(
                sup=quote["supplierName"], pkg=quote["packageLabel"] or quote["package"], total=total
            ),
        }
    # Prototype fallback for the (global) demo quotes.
    demo_quote = reference_repo.get_demo_quote(db, quote_id)
    if demo_quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {
        "quote_id": quote_id,
        "status": "po_issued",
        "message": "Purchase order issued to {sup} for {pkg} ({total}).".format(
            sup=demo_quote["sup"], pkg=demo_quote["pkg"], total=demo_quote["total"]
        ),
    }
