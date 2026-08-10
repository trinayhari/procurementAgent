import json
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FoundSupplier(Base):
    """A supplier discovered via Google Places for one project + buy-package.

    Rows are replaced wholesale per (project, package) on each search, so this is
    a cache of the latest search rather than an append-only log.
    """

    __tablename__ = "found_suppliers"

    # Tenant boundary — every read/write filters on this explicitly.
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), index=True, nullable=False
    )
    package: Mapped[str] = mapped_column(String, nullable=False)  # category key
    name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str] = mapped_column(String, nullable=False, default="")
    distance_miles: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contact_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    material_categories: Mapped[str] = mapped_column(String, nullable=False, default="[]")
    email_source: Mapped[str] = mapped_column(String, nullable=False, default="none")
    place_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    verify_reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "projectId": self.project_id,
            "package": self.package,
            "name": self.name,
            "address": self.address,
            "distanceMiles": self.distance_miles,
            "tier": self.tier,
            "contactName": self.contact_name,
            "email": self.email,
            "phone": self.phone,
            "website": self.website,
            "materialCategories": json.loads(self.material_categories or "[]"),
            "emailSource": self.email_source,
            "placeId": self.place_id,
            "relevanceScore": self.relevance_score,
            "verifyReason": self.verify_reason,
        }
