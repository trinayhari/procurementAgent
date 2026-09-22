"""Request/response shapes for the public approval link (/api/approvals)."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.quote import AwardResult


class ApprovalSupplier(BaseModel):
    """One winner in the recommended award: their lines plus their freight."""

    supplierId: str
    supplierName: str
    subtotal: float  # material for the lines awarded to them
    freight: float
    total: float
    leadDays: Optional[int] = None


class ApprovalPreview(BaseModel):
    """What the approve page shows before the click. `status` is "pending"
    (approvable), "used" (already approved via this link) or "expired"."""

    status: str
    projectId: str
    projectName: str
    package: str
    packageLabel: str
    suppliers: List[ApprovalSupplier] = []
    total: float = 0.0
    material: float = 0.0
    freight: float = 0.0
    leadDays: Optional[int] = None
    # Delivered-cost saving of the recommended split against the cheapest
    # single supplier (0 when the recommendation is a single supplier).
    savings: float = 0.0
    quotesReceived: int = 0
    recipientsTotal: int = 0
    expiresAt: Optional[str] = None
    decidedAt: Optional[str] = None
    decidedByEmail: Optional[str] = None
    # Set when the package was awarded some other way after the link was
    # minted (dashboard, a newer link): the click would need a re-award.
    alreadyAwarded: bool = False


class ApprovalExecuteRequest(BaseModel):
    """Optional identity of the approver (the link itself is the credential).
    Accepts both `decidedByEmail` and `decided_by_email`."""

    model_config = ConfigDict(populate_by_name=True)

    decidedByEmail: Optional[str] = Field(None, alias="decided_by_email")


class ApprovalResult(AwardResult):
    projectId: str
    packageLabel: str
    decidedByEmail: Optional[str] = None
