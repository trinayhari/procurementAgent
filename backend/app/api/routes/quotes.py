from fastapi import APIRouter, HTTPException

from app.repositories import seed
from app.schemas.quote import Quote, SelectResult

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


@router.get("/{quote_id}", response_model=Quote)
def get_quote(quote_id: str):
    quote = seed.get_quote(quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return quote


@router.post("/{quote_id}/select", response_model=SelectResult)
def select_quote(quote_id: str):
    """Command: select a supplier's quote and issue a purchase order."""
    quote = seed.get_quote(quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {
        "quote_id": quote_id,
        "status": "po_issued",
        "message": "Purchase order issued to {sup} for {pkg} ({total}).".format(
            sup=quote["sup"], pkg=quote["pkg"], total=quote["total"]
        ),
    }
