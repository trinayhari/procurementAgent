"""SQLAlchemy ORM models. Importing this package registers every table on
`Base.metadata` (used by Alembic autogenerate and db.init_db)."""
from app.models.project import Project

__all__ = ["Project"]
