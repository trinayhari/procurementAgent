import re
from typing import List, Optional

from pydantic import BaseModel, field_validator

from app.schemas.common import Tone

# Loose on purpose (anything@anything.tld): catches a typo that Gmail would
# reject at send time — when the RFQ goes out — rather than validating
# deliverability. Blank is fine: a supplier can be saved without an email.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_email(v):
    if v is None:
        return v
    v = v.strip()
    if v and not _EMAIL_RE.match(v):
        raise ValueError(f"'{v}' is not a valid email address")
    return v


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

    _email = field_validator("email")(_check_email)


class SupplierUpdate(BaseModel):
    """Edit an existing directory supplier. Every field is optional — only the
    fields that are sent are changed; anything omitted is left untouched."""

    name: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    web: Optional[str] = None
    cats: Optional[List[str]] = None

    _email = field_validator("email")(_check_email)


class SupplierComm(BaseModel):
    tone: Tone
    title: str
    body: str
    time: str
    icon: str


class SupplierDetail(Supplier):
    comms: List[SupplierComm]
