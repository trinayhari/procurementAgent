from typing import List, Optional

from pydantic import BaseModel, Field


class FoundSupplier(BaseModel):
    id: str
    name: str
    address: str
    distanceMiles: float
    tier: int
    contactName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    materialCategories: List[str] = []
    emailSource: str = "none"
    relevanceScore: float = 1.0
    verifyReason: str = ""


class SupplierTier(BaseModel):
    tier: int
    label: str
    suppliers: List[FoundSupplier]


class SupplierSearchResult(BaseModel):
    status: str  # "idle" | "searching" | "done" | "error"
    mocked: bool = False
    radiusMi: int = 0
    package: str = ""
    error: Optional[str] = None
    tiers: List[SupplierTier] = []


class SupplierSearchRequest(BaseModel):
    radius_mi: int = Field(default=75, ge=1, le=250)


class SupplierSearchAccepted(BaseModel):
    status: str
    package: str


class PackageBomItem(BaseModel):
    n: str  # item name
    q: str  # quantity (may be empty when not derivable)


class PackageBom(BaseModel):
    """The BOM line items a buy-package will ask suppliers to quote."""

    package: str
    label: str
    tone: str
    count: int
    items: List[PackageBomItem] = []
    # True when the items come from the shared demo BOM rather than this
    # project's own extracted documents (nothing extracted for it yet).
    seeded: bool = False
    # True when this "package" is actually a hand-built custom BOM document
    # (its items come straight from that document, not a discipline mapping).
    custom: bool = False


class CustomBomSummary(BaseModel):
    """A hand-built custom BOM, surfaced as a selectable package in the
    supplier search alongside the discipline buy-packages."""

    id: str  # the underlying document id — used as the `package` in search/RFQ
    name: str
    count: int
    reviewed: bool = False
