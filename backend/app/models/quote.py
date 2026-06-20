import json
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

_LOGO_COLORS = ["#0a4d8c", "#16a34a", "#0f766e", "#b45309", "#7c3aed", "#334155"]


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace("&", " ").split() if p]
    if not parts:
        return "SU"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _money(v: Optional[float]) -> str:
    return f"${v:,.0f}" if v is not None else "—"


class Quote(Base):
    """A supplier quote received in response to an RFQ.

    Created by the ingest pipeline (Gmail reply → parser) or a deterministic mock
    when Gmail/OpenAI are unconfigured. Numbers are stored numeric so comparison
    can rank them; display strings are derived in to_dict()/to_quote_row().
    """

    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), index=True, nullable=False
    )
    package: Mapped[str] = mapped_column(String, nullable=False)  # category key
    package_label: Mapped[str] = mapped_column(String, nullable=False, default="")
    rfq_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    supplier_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    supplier_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    supplier_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    material_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    freight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lead_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    validity: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Haul distance from the supplier yard to the jobsite (miles) — drives the
    # delivery/logistics view and split-award tradeoffs.
    distance_miles: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    line_items: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String, nullable=False, default="mock")
    source_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="received")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def _logo_bg(self) -> str:
        return _LOGO_COLORS[sum(ord(c) for c in (self.supplier_name or "x")) % len(_LOGO_COLORS)]

    def to_quote_row(self, best: bool = False) -> dict:
        """Shape consumed by the existing Quotes table UI (schemas.quote.Quote)."""
        return {
            "id": self.id,
            "sup": self.supplier_name or "Unknown supplier",
            "pkg": self.package_label or self.package,
            "amount": _money(self.material_cost),
            "freight": _money(self.freight),
            "total": _money(self.total),
            "lead": f"{self.lead_days} days" if self.lead_days is not None else "—",
            "date": self.created_at.strftime("%b %d") if self.created_at else "—",
            "logo": _initials(self.supplier_name),
            "logoBg": self._logo_bg(),
            "best": best,
        }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "projectId": self.project_id,
            "package": self.package,
            "packageLabel": self.package_label,
            "rfqId": self.rfq_id,
            "supplierId": self.supplier_id,
            "supplierName": self.supplier_name,
            "supplierEmail": self.supplier_email,
            "materialCost": self.material_cost,
            "freight": self.freight,
            "total": self.total,
            "leadDays": self.lead_days,
            "deliveryDate": self.delivery_date,
            "validity": self.validity,
            "distanceMiles": self.distance_miles,
            "lineItems": json.loads(self.line_items or "[]"),
            "notes": self.notes,
            "source": self.source,
            "status": self.status,
        }
