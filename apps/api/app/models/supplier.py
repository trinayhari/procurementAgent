import json

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Supplier(Base):
    """A supplier in the project's vendor directory (distinct from the
    geocoded `found_suppliers` discovered via Places search)."""

    __tablename__ = "suppliers"

    # Tenant boundary — every read/write filters on this explicitly.
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )

    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    cats: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    contact: Mapped[str] = mapped_column(String, nullable=False, default="")
    phone: Mapped[str] = mapped_column(String, nullable=False, default="")
    email: Mapped[str] = mapped_column(String, nullable=False, default="")
    web: Mapped[str] = mapped_column(String, nullable=False, default="")
    rfq: Mapped[str] = mapped_column(String, nullable=False, default="")
    rfq_tone: Mapped[str] = mapped_column(String, nullable=False, default="gray")
    last: Mapped[str] = mapped_column(String, nullable=False, default="—")
    quotes: Mapped[str] = mapped_column(String, nullable=False, default="0")
    quote_val: Mapped[str] = mapped_column(String, nullable=False, default="—")
    lead: Mapped[str] = mapped_column(String, nullable=False, default="—")
    logo: Mapped[str] = mapped_column(String, nullable=False, default="SU")
    logo_bg: Mapped[str] = mapped_column(String, nullable=False, default="#334155")
    fin: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "cats": json.loads(self.cats or "[]"),
            "contact": self.contact,
            "phone": self.phone,
            "email": self.email,
            "web": self.web,
            "rfq": self.rfq,
            "rfqTone": self.rfq_tone,
            "last": self.last,
            "quotes": self.quotes,
            "quoteVal": self.quote_val,
            "lead": self.lead,
            "logo": self.logo,
            "logoBg": self.logo_bg,
            "fin": json.loads(self.fin or "{}"),
        }


class SupplierComm(Base):
    """A comms-history entry shown on the supplier detail page.

    Seeded as a shared list (the prototype shows the same history for every
    supplier); ordered by `seq`.

    Deliberately NOT tenant-scoped: rows only ever come from the seed.py
    literals (there is no create/update path), so this is global display data
    identical for every organization.
    """

    __tablename__ = "supplier_comms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    tone: Mapped[str] = mapped_column(String, nullable=False, default="blue")
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time: Mapped[str] = mapped_column(String, nullable=False, default="")
    icon: Mapped[str] = mapped_column(String, nullable=False, default="rfq")

    def to_dict(self) -> dict:
        return {
            "tone": self.tone,
            "title": self.title,
            "body": self.body,
            "time": self.time,
            "icon": self.icon,
        }
