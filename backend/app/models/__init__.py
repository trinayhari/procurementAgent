"""SQLAlchemy ORM models. Importing this package registers every table on
`Base.metadata` (used by Alembic autogenerate and db.init_db)."""
from app.models.audit_event import AuditEvent
from app.models.background_job import BackgroundJob
from app.models.document import Document
from app.models.event import ProjectEvent
from app.models.purchase_decision import PurchaseDecision
from app.models.found_supplier import FoundSupplier
from app.models.project import Project
from app.models.quote import Quote
from app.models.reference import (
    ActivityItem,
    Comparison,
    DashboardMetric,
    DemoQuote,
    DemoRfq,
    GanttBar,
    GanttColumn,
    Milestone,
    OverviewCard,
    PackageProgress,
    RfqFolder,
    SeedLineItemGroup,
)
from app.models.rfq import Rfq
from app.models.supplier import Supplier, SupplierComm
from app.models.timeline_event import TimelineEvent
from app.models.user import User

__all__ = [
    "AuditEvent",
    "BackgroundJob",
    "PurchaseDecision",
    "Project",
    "ProjectEvent",
    "FoundSupplier",
    "Rfq",
    "Quote",
    "Document",
    "Supplier",
    "SupplierComm",
    "DashboardMetric",
    "ActivityItem",
    "OverviewCard",
    "PackageProgress",
    "SeedLineItemGroup",
    "Comparison",
    "Milestone",
    "GanttBar",
    "GanttColumn",
    "RfqFolder",
    "DemoRfq",
    "DemoQuote",
    "TimelineEvent",
    "User",
]
