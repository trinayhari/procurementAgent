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
    # How many schedule events this document contributed to the project
    # timeline (annotated at read time from timeline_events; 0 until the
    # background timeline extraction has run).
    timelineEvents: int = 0
    # Human-in-the-loop review state.
    reviewed: bool = False
    reviewedAt: Optional[str] = None
    edited: bool = False  # True once a human has changed the AI-extracted BOM
    # SHA-256 of the uploaded original (integrity + duplicate detection).
    checksum: Optional[str] = None


class DocumentPreview(BaseModel):
    """Everything the preview panel needs to page through a document.

    Pages are rendered server-side to images, so `pageUrl` is a template with a
    `{page}` placeholder the client substitutes (0-based) — one signed token
    covers every page of this document for the life of the preview session.
    """

    pages: int  # 0 when the document has no renderable pages
    pageUrl: Optional[str] = None
    fileUrl: str  # the original file, for download / open-in-a-new-tab
    expiresInMinutes: int


class PlanType(BaseModel):
    """A registered plan type, surfaced to the upload UI."""

    key: str
    label: str
    description: str
    enabled: bool
    categories: List[str]  # category labels, for display
    # True for the single-document slots (site / building / electrical plan);
    # False for the multi-document "Additional Document" slot. Drives the slot UI.
    singleton: bool = True


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


class ManualBomCreate(BaseModel):
    """Body for creating a hand-built custom BOM document (no file upload)."""

    name: str
    projectId: str
