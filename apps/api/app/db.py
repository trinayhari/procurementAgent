"""SQLAlchemy engine, session factory, and the FastAPI session dependency.

The schema is owned by Alembic (see apps/api/migrations). `init_db()` is a dev
convenience that creates any missing tables and seeds the starter projects so the
app works on a fresh checkout without manually running migrations first.
"""
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# SQLite needs check_same_thread=False to be shared across FastAPI's threadpool;
# the flag is harmless/ignored for other backends.
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


# The organization demo/prototype data is seeded into. Real signups each get
# their own org, so demo content is never visible to them.
DEMO_ORG_ID = "demo"
DEMO_ORG_NAME = "Meridian Civil Co."

# Where rows that predate multi-tenancy land. Must match migration
# 0017_organizations so a dev DB (create_all + _ensure_dev_columns) and a
# migrated DB agree.
BACKFILL_ORG_ID = "default"
BACKFILL_ORG_NAME = "Default Organization"

# Tables carrying `organization_id`. The reference/display tables and
# supplier_comms are deliberately absent — they hold only seeded literals that
# are identical for every tenant (see models/reference.py).
SCOPED_TABLES = (
    "users",
    "projects",
    "documents",
    "suppliers",
    "rfqs",
    "quotes",
    "found_suppliers",
    "timeline_events",
    "project_events",
    "purchase_decisions",
    "audit_events",
    "background_jobs",
    "lenders",
    "package_budgets",
    "inbound_emails",
    "approval_tokens",
    "package_recommendations",
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create missing tables and seed starter projects if the table is empty.

    Importing models here (not at module top) avoids a circular import and
    ensures they're registered on Base.metadata before create_all().
    """
    from app import models  # noqa: F401  (registers tables on Base.metadata)
    from app.repositories import documents as documents_repo
    from app.repositories import organizations as organizations_repo
    from app.repositories import projects as projects_repo
    from app.repositories import quotes as quotes_repo
    from app.repositories import reference as reference_repo
    from app.repositories import suppliers as suppliers_repo
    from app.repositories import users as users_repo

    Base.metadata.create_all(bind=engine)
    _ensure_dev_columns()
    with SessionLocal() as db:
        if not settings.seed_demo_data:
            # Production default: no prototype/demo data and no demo account.
            # The app shows only real, user-generated content; use
            # /api/auth/register to create the first user.
            return
        # Everything seeded below belongs to the demo user's own organization —
        # demo data must not be visible to real signups, which get their own.
        org = organizations_repo.ensure_organization(db, DEMO_ORG_ID, DEMO_ORG_NAME)
        # Demo login account (jordan@meridiancivil.com / procureai) so the
        # auth-gated UI is usable in demo environments without registering.
        users_repo.seed_demo_user(db, org.id)
        projects_repo.seed_starter_projects(db, org.id)
        documents_repo.seed_starter_documents(db, org.id)
        # Reference/display data (dashboard, suppliers, comparison, timeline, the
        # demo RFQ inbox + quote list) — seeded once so the app renders fully.
        # The reference tables themselves are global (identical for every org);
        # only the supplier directory is tenant data.
        suppliers_repo.seed_suppliers(db, org.id)
        reference_repo.seed_reference_data(db)
        # Seed priced sample quotes for the demo project so the line-by-line
        # comparison + award flow works on a fresh checkout (idempotent).
        quotes_repo.seed_sample_quotes(db, org.id, "riverside")


def _ensure_dev_columns() -> None:
    """Add columns introduced after a table was first create_all()'d.

    `create_all` never ALTERs existing tables, so a dev DB created before a new
    column won't have it. Alembic owns real migrations; this only keeps the
    zero-config dev DB usable without a manual `alembic upgrade`.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "quotes" in tables:
        cols = {c["name"] for c in inspector.get_columns("quotes")}
        if "distance_miles" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE quotes ADD COLUMN distance_miles FLOAT"))
    if "timeline_events" in tables:
        cols = {c["name"] for c in inspector.get_columns("timeline_events")}
        with engine.begin() as conn:
            if "done" not in cols:
                conn.execute(text("ALTER TABLE timeline_events ADD COLUMN done BOOLEAN NOT NULL DEFAULT 0"))
            if "done_at" not in cols:
                conn.execute(text("ALTER TABLE timeline_events ADD COLUMN done_at VARCHAR NOT NULL DEFAULT ''"))
    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "cc_email" not in cols:
            with engine.begin() as conn:
                if "sender_email" in cols:
                    # Pre-0016 dev DB: same column, new meaning (Cc, not From).
                    conn.execute(text("ALTER TABLE users RENAME COLUMN sender_email TO cc_email"))
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN cc_email VARCHAR"))
    if "rfqs" in tables:
        cols = {c["name"] for c in inspector.get_columns("rfqs")}
        with engine.begin() as conn:
            if "kind" not in cols:
                # Mirrors 0020_rfq_kind_attachments: pre-existing RFQs are all
                # materials RFQs.
                conn.execute(text("ALTER TABLE rfqs ADD COLUMN kind VARCHAR NOT NULL DEFAULT 'materials'"))
            if "attachments" not in cols:
                conn.execute(text("ALTER TABLE rfqs ADD COLUMN attachments TEXT NOT NULL DEFAULT '[]'"))
    if "organization_invites" in tables:
        cols = {c["name"] for c in inspector.get_columns("organization_invites")}
        with engine.begin() as conn:
            # Mirrors 0024_email_delivery_records.
            if "emailed_at" not in cols:
                conn.execute(text("ALTER TABLE organization_invites ADD COLUMN emailed_at DATETIME"))
            if "email_error" not in cols:
                conn.execute(text("ALTER TABLE organization_invites ADD COLUMN email_error VARCHAR"))
    if "purchase_decisions" in tables:
        cols = {c["name"] for c in inspector.get_columns("purchase_decisions")}
        with engine.begin() as conn:
            # Mirrors 0024_email_delivery_records.
            if "notifications" not in cols:
                conn.execute(text("ALTER TABLE purchase_decisions ADD COLUMN notifications TEXT NOT NULL DEFAULT '{}'"))
            if "status" not in cols:
                conn.execute(text("ALTER TABLE purchase_decisions ADD COLUMN status VARCHAR NOT NULL DEFAULT 'active'"))
            if "superseded_by" not in cols:
                conn.execute(text("ALTER TABLE purchase_decisions ADD COLUMN superseded_by VARCHAR"))
            if "po_numbers" not in cols:
                conn.execute(text("ALTER TABLE purchase_decisions ADD COLUMN po_numbers TEXT NOT NULL DEFAULT '[]'"))
    if "organizations" in tables:
        cols = {c["name"] for c in inspector.get_columns("organizations")}
        if "po_counter" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE organizations ADD COLUMN po_counter INTEGER NOT NULL DEFAULT 0"))
    if "projects" in tables:
        # Mirrors 0023_computed_project_rows: the seeded display columns are
        # gone (rows are computed). A dev DB created before that would still
        # carry them as NOT NULL, so inserts of new projects would fail.
        cols = {c["name"] for c in inspector.get_columns("projects")}
        stale = [c for c in ("stage", "stage_tone", "progress", "suppliers", "rfqs", "quotes", "risk", "risk_tone", "bar_color") if c in cols]
        if stale:
            with engine.begin() as conn:
                for col in stale:
                    conn.execute(text(f"ALTER TABLE projects DROP COLUMN {col}"))
    _ensure_organization_column(inspector, tables)


def _ensure_organization_column(inspector, tables: set) -> None:
    """Backfill `organization_id` on a dev DB created before multi-tenancy.

    Mirrors migration 0017_organizations for the zero-config path: existing rows
    land in the same `default` organization the migration uses, so a dev DB and a
    migrated one behave identically.
    """
    missing = [
        t
        for t in SCOPED_TABLES
        if t in tables
        and "organization_id" not in {c["name"] for c in inspector.get_columns(t)}
    ]
    if not missing:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizations (seq, id, name, created_at) "
                "SELECT :seq, :id, :name, CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE id = :id)"
            ),
            {"seq": 1, "id": BACKFILL_ORG_ID, "name": BACKFILL_ORG_NAME},
        )
        for table in missing:
            conn.execute(
                text(
                    f"ALTER TABLE {table} ADD COLUMN organization_id VARCHAR "
                    f"NOT NULL DEFAULT '{BACKFILL_ORG_ID}'"
                )
            )
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_{table}_organization_id "
                    f"ON {table} (organization_id)"
                )
            )
