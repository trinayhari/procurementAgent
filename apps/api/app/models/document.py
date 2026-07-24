import json
from typing import List, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Document(Base):
    """An uploaded plan set (or seeded demo doc) scoped to one project.

    Persisting these to SQLite (rather than the old in-memory store) means
    uploads — and the project they belong to — survive a backend restart. The
    extracted BOM groups are stored alongside the record as a JSON blob in
    `line_items` so re-analysis isn't required after a restart.
    """

    __tablename__ = "documents"

    # Monotonic insertion-order key (assigned by the repo); the UI lists
    # newest-first via ORDER BY seq DESC.
    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False, default="Uploaded")
    date: Mapped[str] = mapped_column(String, nullable=False, default="—")
    status: Mapped[str] = mapped_column(String, nullable=False, default="Processing")
    status_tone: Mapped[str] = mapped_column(String, nullable=False, default="blue")
    items: Mapped[str] = mapped_column(String, nullable=False, default="—")
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_file: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # SHA-256 of the uploaded original (integrity + duplicate detection).
    checksum_sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    plan_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Extracted BOM groups (JSON). NULL means "not yet extracted"; seed docs with
    # no own BOM fall back to the shared seed.LINE_ITEMS in the repository.
    line_items: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def get_line_items(self) -> Optional[List[dict]]:
        if self.line_items is None:
            return None
        return json.loads(self.line_items)

    def to_dict(self) -> dict:
        """Shape a row into the camelCase payload the Document schema expects.

        `sourcePath` is intentionally omitted (it's an internal disk path); the
        UI uses `hasFile` + the `/file` endpoint to preview the original.
        """
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "date": self.date,
            "status": self.status,
            "statusTone": self.status_tone,
            "items": self.items,
            "pages": self.pages,
            "processing": self.processing,
            "hasFile": self.has_file,
            "planType": self.plan_type,
            "summary": self.summary,
            "mocked": self.mocked,
            "error": self.error,
            "reviewed": self.reviewed,
            "checksum": self.checksum_sha256,
            "reviewedAt": self.reviewed_at,
            "edited": self.edited,
        }
