import json
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PurchaseDecision(Base):
    """The durable record of a package award — who bought what, from whom, why.

    Awarding used to be just a status flip on the winning quotes; this table
    captures the decision itself: the line→supplier selections, totals, the
    strategy used, and the user who made the call.
    """

    __tablename__ = "purchase_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    package: Mapped[str] = mapped_column(String, nullable=False)
    package_label: Mapped[str] = mapped_column(String, nullable=False, default="")
    strategy: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    selections: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON line→supplier
    supplier_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    suppliers: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON display names
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    material: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    freight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    lead_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    po_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decided_by: Mapped[str] = mapped_column(String, nullable=False, default="")
    decided_by_email: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "projectId": self.project_id,
            "package": self.package,
            "packageLabel": self.package_label,
            "strategy": self.strategy,
            "selections": json.loads(self.selections or "{}"),
            "supplierIds": json.loads(self.supplier_ids or "[]"),
            "suppliers": json.loads(self.suppliers or "[]"),
            "total": self.total,
            "material": self.material,
            "freight": self.freight,
            "leadDays": self.lead_days,
            "poCount": self.po_count,
            "decidedBy": self.decided_by,
            "decidedByEmail": self.decided_by_email,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
