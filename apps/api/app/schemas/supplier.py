from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import Tone


class SupplierFinancials(BaseModel):
    submitted: str
    total: str
    avg: str


class Supplier(BaseModel):
    id: str
    name: str
    cats: List[str]
    contact: str
    phone: str
    email: str
    web: str
    rfq: str
    rfqTone: Tone
    last: str
    quotes: str
    quoteVal: str
    lead: str
    logo: str
    logoBg: str
    fin: SupplierFinancials


class SupplierCreate(BaseModel):
    """Add a supplier to the directory — manually, or from a search result.

    Only a name is required; the rest is optional contact/category detail."""

    name: str
    contact: str = ""
    phone: str = ""
    email: str = ""
    web: str = ""
    cats: List[str] = []


class SupplierUpdate(BaseModel):
    """Edit an existing directory supplier. Every field is optional — only the
    fields that are sent are changed; anything omitted is left untouched."""

    name: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    web: Optional[str] = None
    cats: Optional[List[str]] = None


class SupplierComm(BaseModel):
    tone: Tone
    title: str
    body: str
    time: str
    icon: str


class SupplierDetail(Supplier):
    comms: List[SupplierComm]
