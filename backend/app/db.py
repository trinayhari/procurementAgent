"""SQLAlchemy engine, session factory, and the FastAPI session dependency.

The schema is owned by Alembic (see backend/migrations). `init_db()` is a dev
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
    from app.repositories import projects as projects_repo
    from app.repositories import quotes as quotes_repo
    from app.repositories import reference as reference_repo
    from app.repositories import suppliers as suppliers_repo
    from app.repositories import users as users_repo

    Base.metadata.create_all(bind=engine)
    _ensure_dev_columns()
    with SessionLocal() as db:
        # Demo login account (jordan@meridiancivil.com / procureai) so the
        # auth-gated UI is usable on a fresh checkout. Kept regardless of the
        # demo-data flag so there's always a way in before registering.
        users_repo.seed_demo_user(db)
        if not settings.seed_demo_data:
            # Production default: no prototype/demo data. The app shows only
            # real, user-generated content (empty states until data exists).
            return
        projects_repo.seed_starter_projects(db)
        documents_repo.seed_starter_documents(db)
        # Reference/display data (dashboard, suppliers, comparison, timeline, the
        # demo RFQ inbox + quote list) — seeded once so the app renders fully.
        suppliers_repo.seed_suppliers(db)
        reference_repo.seed_reference_data(db)
        # Seed priced sample quotes for the demo project so the line-by-line
        # comparison + award flow works on a fresh checkout (idempotent).
        quotes_repo.seed_sample_quotes(db, "riverside")


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
    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "sender_email" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN sender_email VARCHAR"))
