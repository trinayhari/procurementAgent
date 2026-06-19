from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import DocStatus, Tone


class Document(BaseModel):
    id: str
    name: str
    type: str
    date: str
    status: DocStatus
    statusTone: Tone
    items: str
    pages: int
    processing: bool = False
    hasFile: bool = False  # True when the original file is on disk and previewable
    # Extraction metadata (populated for uploaded docs).
    planType: Optional[str] = None
    summary: Optional[str] = None
    mocked: bool = False
    error: Optional[str] = None
    # Human-in-the-loop review state.
    reviewed: bool = False
    reviewedAt: Optional[str] = None
    edited: bool = False  # True once a human has changed the AI-extracted BOM


class PlanType(BaseModel):
    """A registered plan type, surfaced to the upload UI."""

    key: str
    label: str
    description: str
    enabled: bool
    categories: List[str]  # category labels, for display


class LineItem(BaseModel):
    n: str  # name, e.g. '12" DI Pipe, Class 350'
    q: str  # quantity, e.g. "2,400 LF"


class LineItemGroup(BaseModel):
    group: str
    count: int
    tone: Tone
    items: List[LineItem]


class LineItemsUpdate(BaseModel):
    """Body for saving a human-edited BOM (full replacement of the groups)."""

    groups: List[LineItemGroup]
