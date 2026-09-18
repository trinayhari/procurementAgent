from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Quote(BaseModel):
    id: str
    sup: str
    pkg: str  # display label
    # Package key ("water", or a custom BOM / trade scope document id) — what
    # the comparison + award routes take. Empty for the seeded demo quotes,
    # whose label maps to a key server-side.
    package: str = ""
    amount: str
    freight: str
    total: str
    lead: str
    date: str
    logo: str
    logoBg: str
    best: bool = False


class ComparisonSupplier(BaseModel):
    name: str
    logo: str
    logoBg: str
    rec: bool = False


class ComparisonRow(BaseModel):
    label: str
    vals: List[str]
    best: int
    emph: bool = False


class Comparison(BaseModel):
    pkg: str
    suppliers: List[ComparisonSupplier]
    rows: List[ComparisonRow]
    recommendation: str
    reasons: List[str]
    savings: str
    savingsNote: str


class LineCompareSupplier(BaseModel):
    id: str
    name: str
    logo: str
    logoBg: str
    leadDays: Optional[int] = None
    distanceMiles: Optional[float] = None
    freight: Optional[float] = None
    total: Optional[float] = None


class LineCompareCell(BaseModel):
    supplierId: str
    unitPrice: Optional[float] = None
    extended: Optional[float] = None
    leadDays: Optional[int] = None
    available: bool = True
    best: bool = False


class LineCompareRow(BaseModel):
    name: str
    qty: str = ""
    cells: List[LineCompareCell]
    bestSupplierId: Optional[str] = None
    # True when no supplier has priced this line yet ("quote pending"): shown for
    # reference but excluded from the award strategies.
    pending: bool = False


class AwardOption(BaseModel):
    key: str  # "mix" | "fastest" | "single"
    label: str
    total: float
    material: float
    freight: float
    leadDays: Optional[int] = None
    suppliersUsed: int
    deliveries: int
    maxDistance: Optional[float] = None
    savings: float = 0.0
    note: str = ""
    selections: Dict[str, str] = {}  # lineName -> supplierId


class LastAward(BaseModel):
    """The most recent purchase decision for this package, when there is one."""

    decidedAt: Optional[str] = None
    decidedByEmail: str = ""
    suppliers: List[str] = []
    total: float = 0
    poCount: int = 0


class LineComparison(BaseModel):
    pkg: str
    package: str
    budget: Optional[float] = None
    suppliers: List[LineCompareSupplier]
    lines: List[LineCompareRow]
    options: List[AwardOption]
    recommendedOption: str = "mix"
    # Set when the package was already awarded: the UI shows it and asks for
    # an explicit re-award rather than re-issuing (and re-emailing) the POs
    # on a stray click.
    lastAward: Optional[LastAward] = None


class PackageBudgetUpdate(BaseModel):
    """Set (a positive amount) or clear (null) the budget for a package."""

    budget: Optional[float] = Field(default=None, gt=0, le=1e12)


class PackageBudget(BaseModel):
    package: str
    budget: Optional[float] = None


class AwardRequest(BaseModel):
    selections: Dict[str, str]  # lineName -> supplierId
    strategy: Optional[str] = None
    # A package that already has a purchase decision is refused (409) unless
    # the caller explicitly supersedes it: every award issues POs and emails
    # every supplier, so a replayed or double-submitted request must not.
    supersede: bool = False


class AwardResult(BaseModel):
    status: str
    message: str
    total: float
    material: float
    freight: float
    leadDays: Optional[int] = None
    suppliers: List[str]
    poCount: int


class SelectResult(BaseModel):
    quote_id: str
    status: str
    message: str


class PurchaseDecision(BaseModel):
    """A recorded award for a package — who bought what, from whom, decided by
    whom. Surfaced on the comparison screen so a package that was already
    awarded is never re-awarded (and suppliers re-notified) by accident."""

    id: str
    projectId: str
    package: str
    packageLabel: str
    strategy: Optional[str] = None
    selections: Dict[str, str] = {}
    supplierIds: List[str] = []
    suppliers: List[str] = []
    total: float
    material: float = 0.0
    freight: float = 0.0
    leadDays: Optional[int] = None
    poCount: int = 0
    decidedBy: Optional[str] = None
    decidedByEmail: Optional[str] = None
    createdAt: Optional[str] = None


class QuoteIngestResult(BaseModel):
    """Status payload for the quote-ingest poller (mirrors the search poller)."""

    status: str  # "ingesting" | "done" | "error" | "idle"
    mocked: bool = False
    ingested: int = 0
    total: int = 0
    error: Optional[str] = None
