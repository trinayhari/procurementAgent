"""SQLAlchemy engine, session factory, and the FastAPI session dependency.

The schema is owned by Alembic (see backend/migrations). `init_db()` is a dev
convenience that creates any missing tables and seeds the starter projects so the
app works on a fresh checkout without manually running migrations first.
"""
from typing import Iterator

from sqlalchemy import create_engine
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
    from app.repositories import projects as projects_repo

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        projects_repo.seed_starter_projects(db)
