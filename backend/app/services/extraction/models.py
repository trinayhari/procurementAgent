"""Pydantic models for the extraction pipeline.

`VisionExtraction` is the *structured output* contract we force GPT-4.1 to fill:
keep it flat and unambiguous so the model reliably conforms. Everything the
frontend renders (grouping, tones, display strings) is derived from these in
`service.py` — the model is never asked to produce presentation data.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class ExtractedItem(BaseModel):
    """A single Bill-of-Materials line item read off a plan sheet."""

    name: str = Field(description="Full material description, e.g. '12\" DI Pipe, Class 350'.")
    quantity: Optional[float] = Field(
        default=None, description="Numeric quantity if shown or derivable, else null."
    )
    unit: Optional[str] = Field(
        default=None, description="Unit of measure: LF, EA, SY, CY, TON, etc. Null if unknown."
    )
    spec: Optional[str] = Field(
        default=None, description="Material/spec detail: size, class, material, schedule."
    )
    feature: Optional[str] = Field(
        default=None,
        description=(
            "Identifier of the specific physical run/structure this item is, e.g. "
            "'Waterline A', 'WW Line B', 'Storm Line A', 'MH-3'. Used to deduplicate the "
            "same feature seen on multiple sheets vs. summing genuinely different features."
        ),
    )
    source: Optional[str] = Field(
        default=None, description="Where it was read from: sheet number, callout, schedule, or legend."
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="0-1 confidence this item is correct and complete."
    )
    assumptions: Optional[str] = Field(
        default=None, description="Any assumption made (e.g. estimated count, ambiguous callout)."
    )


class ExtractedBom(BaseModel):
    """All line items found for one BOM category (discipline) within a plan."""

    category: str = Field(
        description="The category KEY this BOM belongs to (must be one of the keys provided in the prompt)."
    )
    items: List[ExtractedItem] = Field(default_factory=list)


class VisionExtraction(BaseModel):
    """Top-level structured output returned by the vision model."""

    plan_type: str = Field(description="Detected plan type key (echo the requested type if it matches).")
    sheet_summary: Optional[str] = Field(
        default=None, description="One-sentence description of what these sheets contain."
    )
    boms: List[ExtractedBom] = Field(
        default_factory=list, description="One entry per category that has items. Omit empty categories."
    )
    unmatched_notes: Optional[str] = Field(
        default=None,
        description="Materials seen that did not fit any provided category, described briefly.",
    )
