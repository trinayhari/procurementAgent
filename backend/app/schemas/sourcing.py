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


class AdHocSupplierSearchRequest(BaseModel):
    """Free-text supplier search for an ad-hoc RFQ (no fixed buy-package)."""

    query: str
    radius_mi: int = Field(default=75, ge=1, le=250)


class SupplierSearchAccepted(BaseModel):
    status: str
    package: str
