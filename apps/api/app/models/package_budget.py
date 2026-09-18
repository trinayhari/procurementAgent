"""ORM model for a per-package budget on a project.

A "package" is whatever the buyer sources as one unit — a preset discipline
category ("water"), a hand-built custom BOM or a subcontractor trade scope
(both keyed by their document id). None of those has a single row to hang a
budget on, so budgets live here, keyed by (organization, project, package).
Set inline on the Quote Comparison screen; the comparison shows an
over/under-budget line only when a budget exists.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PackageBudget(Base):
    __tablename__ = "package_budgets"
    __table_args__ = (
        UniqueConstraint("organization_id", "project_id", "package", name="uq_package_budget"),
    )

    # Tenant boundary — every read/write filters on this explicitly.
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    package: Mapped[str] = mapped_column(String, nullable=False)
    budget: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
