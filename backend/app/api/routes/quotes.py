from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories import quotes as quotes_repo
from app.repositories import seed
from app.schemas.quote import SelectResult

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


@router.get("/{quote_id}")
def get_quote(quote_id: str, db: Session = Depends(get_db)):
    quote = quotes_repo.get_quote(db, quote_id)
    if quote is not None:
        return quote
    seed_quote = seed.get_quote(quote_id)  # prototype fallback
    if seed_quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return seed_quote


@router.post("/{quote_id}/select", response_model=SelectResult)
def select_quote(quote_id: str, db: Session = Depends(get_db)):
    """Command: select a supplier's quote and issue a purchase order."""
    quote = quotes_repo.select_quote(db, quote_id)
    if quote is not None:
        total = f"${quote['total']:,.0f}" if quote.get("total") is not None else "—"
        return {
            "quote_id": quote_id,
            "status": "po_issued",
            "message": "Purchase order issued to {sup} for {pkg} ({total}).".format(
                sup=quote["supplierName"], pkg=quote["packageLabel"] or quote["package"], total=total
            ),
        }
    # Prototype fallback for the seed quotes.
    seed_quote = seed.get_quote(quote_id)
    if seed_quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {
        "quote_id": quote_id,
        "status": "po_issued",
        "message": "Purchase order issued to {sup} for {pkg} ({total}).".format(
            sup=seed_quote["sup"], pkg=seed_quote["pkg"], total=seed_quote["total"]
        ),
    }
