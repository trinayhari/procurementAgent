from typing import List, Optional

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
