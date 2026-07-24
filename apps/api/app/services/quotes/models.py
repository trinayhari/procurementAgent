"""Structured-output contract for parsing a supplier quote out of an email/PDF.

Kept flat and explicit so OpenAI Structured Outputs reliably conforms, mirroring
the extraction pipeline's VisionExtraction model.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class ParsedQuoteLine(BaseModel):
    name: str = Field(description="Line-item description as quoted.")
    quantity: Optional[str] = Field(default=None, description="Quantity with unit, if present.")
    unit_price: Optional[float] = Field(default=None, description="Per-unit price in USD, if present.")
    extended: Optional[float] = Field(default=None, description="Extended/line total in USD, if present.")
    lead_days: Optional[int] = Field(
        default=None,
        description=(
            "Lead time for THIS line in calendar days, if stated. In-stock/immediate → 0; "
            "a range like '2-3 weeks' → the longer end in days (21). Null if not stated."
        ),
    )


class ParsedQuote(BaseModel):
    """Numbers a comparison can rank. All optional — suppliers omit fields."""

    is_quote: bool = Field(
        description="True if this message actually contains a price quote (vs. an acknowledgement)."
    )
    supplier_name: Optional[str] = Field(default=None, description="Quoting company name, if stated.")
    material_cost: Optional[float] = Field(default=None, description="Subtotal of materials in USD.")
    freight: Optional[float] = Field(default=None, description="Freight/shipping charge in USD.")
    total: Optional[float] = Field(default=None, description="Grand total in USD (incl. freight).")
    lead_days: Optional[int] = Field(default=None, description="Lead time in calendar days.")
    delivery_date: Optional[str] = Field(default=None, description="Promised delivery date if stated.")
    validity: Optional[str] = Field(default=None, description="How long the quote is valid (e.g. '30 days').")
    line_items: List[ParsedQuoteLine] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None, description="Any caveats, substitutions, or terms.")
