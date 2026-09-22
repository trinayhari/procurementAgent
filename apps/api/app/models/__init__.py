"""SQLAlchemy ORM models. Importing this package registers every table on
`Base.metadata` (used by Alembic autogenerate and db.init_db)."""
from app.models.audit_event import AuditEvent
from app.models.background_job import BackgroundJob
from app.models.document import Document
from app.models.event import ProjectEvent
from app.models.purchase_decision import PurchaseDecision
from app.models.found_supplier import FoundSupplier
from app.models.inbound_email import InboundEmail
from app.models.lender import Lender
from app.models.organization import Organization
from app.models.organization_invite import OrganizationInvite
from app.models.package_budget import PackageBudget
from app.models.project import Project
from app.models.quote import Quote
from app.models.reference import (
    ActivityItem,
    Comparison,
    DemoRfq,
    GanttBar,
    GanttColumn,
    Milestone,
    RfqFolder,
    SeedLineItemGroup,
)
from app.models.rfq import Rfq
from app.models.slack_channel_link import SlackChannelLink
from app.models.slack_installation import SlackInstallation
from app.models.supplier import Supplier, SupplierComm
from app.models.timeline_event import TimelineEvent
from app.models.user import User

__all__ = [
    "AuditEvent",
    "Organization",
    "OrganizationInvite",
    "PackageBudget",
    "BackgroundJob",
    "PurchaseDecision",
    "Project",
    "ProjectEvent",
    "FoundSupplier",
    "InboundEmail",
    "SlackInstallation",
    "SlackChannelLink",
    "Rfq",
    "Quote",
    "Document",
    "Supplier",
    "SupplierComm",
    "ActivityItem",
    "SeedLineItemGroup",
    "Comparison",
    "Milestone",
    "GanttBar",
    "GanttColumn",
    "RfqFolder",
    "DemoRfq",
    "TimelineEvent",
    "Lender",
    "User",
]
