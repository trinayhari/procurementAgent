from typing import Dict, List, Optional

from pydantic import BaseModel


class Quote(BaseModel):
    id: str
    sup: str
    pkg: str
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


class LineComparison(BaseModel):
    pkg: str
    package: str
    budget: Optional[float] = None
    suppliers: List[LineCompareSupplier]
    lines: List[LineCompareRow]
    options: List[AwardOption]
    recommendedOption: str = "mix"


class AwardRequest(BaseModel):
    selections: Dict[str, str]  # lineName -> supplierId
    strategy: Optional[str] = None


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


class QuoteIngestResult(BaseModel):
    """Status payload for the quote-ingest poller (mirrors the search poller)."""

    status: str  # "ingesting" | "done" | "error" | "idle"
    mocked: bool = False
    ingested: int = 0
    total: int = 0
    error: Optional[str] = None
