"""ORM models for the prototype's reference/display data.

These tables back the dashboard, project workspace cards, vendor comparison,
timeline, and the demo RFQ inbox / quote list. They're seeded once on first run
from the literals in app/repositories/seed.py so the app renders fully, but they
now persist (and can be edited) like any other entity rather than living in a
process-memory list that's lost on restart.

Deeply-nested display structures (comparison rows, BOM items, RFQ threads) are
stored as JSON text columns rather than over-normalised into many child tables.

Deliberately NOT tenant-scoped: every row here comes from the seed.py literals
(there is no user write path), so it is global display/lookup data identical for
all organizations and carries no customer content. Adding `organization_id`
would only duplicate the same demo rows per tenant.
"""
import json

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DashboardMetric(Base):
    __tablename__ = "dashboard_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    delta: Mapped[str] = mapped_column(String, nullable=False, default="")
    sub: Mapped[str] = mapped_column(String, nullable=False, default="")
    up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    down: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_dict(self) -> dict:
        return {
            "label": self.label, "value": self.value, "delta": self.delta,
            "sub": self.sub, "up": self.up, "down": self.down,
            "ai": self.ai, "risk": self.risk,
        }


class ActivityItem(Base):
    __tablename__ = "activity_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    icon: Mapped[str] = mapped_column(String, nullable=False)
    tone: Mapped[str] = mapped_column(String, nullable=False, default="blue")
    title: Mapped[str] = mapped_column(String, nullable=False)
    meta: Mapped[str] = mapped_column(String, nullable=False, default="")
    time: Mapped[str] = mapped_column(String, nullable=False, default="")

    def to_dict(self) -> dict:
        return {
            "icon": self.icon, "tone": self.tone, "title": self.title,
            "meta": self.meta, "time": self.time,
        }


class OverviewCard(Base):
    __tablename__ = "overview_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    sub: Mapped[str] = mapped_column(String, nullable=False, default="")
    icon: Mapped[str] = mapped_column(String, nullable=False, default="file")
    tone: Mapped[str] = mapped_column(String, nullable=False, default="blue")
    ai: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_dict(self) -> dict:
        return {
            "label": self.label, "value": self.value, "sub": self.sub,
            "icon": self.icon, "tone": self.tone, "ai": self.ai,
        }


class PackageProgress(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tone: Mapped[str] = mapped_column(String, nullable=False, default="blue")

    def to_dict(self) -> dict:
        return {"name": self.name, "pct": self.pct, "tone": self.tone}


class SeedLineItemGroup(Base):
    """The shared fallback BOM served for projects/docs with no extracted items."""

    __tablename__ = "line_item_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    group: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tone: Mapped[str] = mapped_column(String, nullable=False, default="blue")
    items: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON

    def to_dict(self) -> dict:
        return {
            "group": self.group, "count": self.count, "tone": self.tone,
            "items": json.loads(self.items or "[]"),
        }


class Comparison(Base):
    """Quote-comparison matrix for one buy-package, keyed by package label."""

    __tablename__ = "comparisons"

    pkg: Mapped[str] = mapped_column(String, primary_key=True)
    suppliers: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    rows: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    recommendation: Mapped[str] = mapped_column(String, nullable=False, default="")
    reasons: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    savings: Mapped[str] = mapped_column(String, nullable=False, default="")
    savings_note: Mapped[str] = mapped_column(String, nullable=False, default="")

    def to_dict(self) -> dict:
        return {
            "pkg": self.pkg,
            "suppliers": json.loads(self.suppliers or "[]"),
            "rows": json.loads(self.rows or "[]"),
            "recommendation": self.recommendation,
            "reasons": json.loads(self.reasons or "[]"),
            "savings": self.savings,
            "savingsNote": self.savings_note,
        }


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="Upcoming")
    desc: Mapped[str] = mapped_column(String, nullable=False, default="")
    tone: Mapped[str] = mapped_column(String, nullable=False, default="gray")
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "date": self.date, "status": self.status,
            "desc": self.desc, "tone": self.tone, "done": self.done,
            "active": self.active,
        }


class GanttBar(Base):
    __tablename__ = "gantt_bars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 'len' in JSON
    tone: Mapped[str] = mapped_column(String, nullable=False, default="blue")
    label: Mapped[str] = mapped_column(String, nullable=False, default="")
    warn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "start": self.start, "len": self.length,
            "tone": self.tone, "label": self.label, "warn": self.warn,
        }


class GanttColumn(Base):
    __tablename__ = "gantt_columns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)


class RfqFolder(Base):
    __tablename__ = "rfq_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[str] = mapped_column(String, nullable=False, default="0")

    def to_dict(self) -> dict:
        return {"name": self.name, "count": self.count}


class DemoRfq(Base):
    """A prototype RFQ-inbox entry (plus its email thread).

    Distinct from the generated `rfqs` table (those are created by the sourcing
    flow); these seed the RFQ inbox UI so it renders before any RFQ is generated.
    """

    __tablename__ = "demo_rfqs"

    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sup: Mapped[str] = mapped_column(String, nullable=False)
    pkg: Mapped[str] = mapped_column(String, nullable=False)
    folder: Mapped[str] = mapped_column(String, nullable=False, default="Draft")
    status: Mapped[str] = mapped_column(String, nullable=False, default="Draft")
    status_tone: Mapped[str] = mapped_column(String, nullable=False, default="gray")
    preview: Mapped[str] = mapped_column(String, nullable=False, default="")
    time: Mapped[str] = mapped_column(String, nullable=False, default="—")
    unread: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    logo: Mapped[str] = mapped_column(String, nullable=False, default="RF")
    logo_bg: Mapped[str] = mapped_column(String, nullable=False, default="#334155")
    thread: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON

    def to_dict(self) -> dict:
        return {
            "id": self.id, "sup": self.sup, "pkg": self.pkg, "folder": self.folder,
            "status": self.status, "statusTone": self.status_tone,
            "preview": self.preview, "time": self.time, "unread": self.unread,
            "logo": self.logo, "logoBg": self.logo_bg,
        }

    def to_detail(self) -> dict:
        return {**self.to_dict(), "thread": json.loads(self.thread or "[]")}


class DemoQuote(Base):
    """A prototype quote-table row (display strings); fallback before real
    quotes are ingested into the numeric `quotes` table."""

    __tablename__ = "demo_quotes"

    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sup: Mapped[str] = mapped_column(String, nullable=False)
    pkg: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[str] = mapped_column(String, nullable=False, default="—")
    freight: Mapped[str] = mapped_column(String, nullable=False, default="—")
    total: Mapped[str] = mapped_column(String, nullable=False, default="—")
    lead: Mapped[str] = mapped_column(String, nullable=False, default="—")
    date: Mapped[str] = mapped_column(String, nullable=False, default="—")
    logo: Mapped[str] = mapped_column(String, nullable=False, default="SU")
    logo_bg: Mapped[str] = mapped_column(String, nullable=False, default="#334155")
    best: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "sup": self.sup, "pkg": self.pkg, "amount": self.amount,
            "freight": self.freight, "total": self.total, "lead": self.lead,
            "date": self.date, "logo": self.logo, "logoBg": self.logo_bg,
            "best": self.best,
        }
