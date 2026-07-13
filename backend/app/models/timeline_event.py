"""ORM model for extracted timeline events.

One row per milestone/phase extracted from a project document. Events are keyed
by both project (the schedule is built per-project) and source document (so a
re-analysis or deletion of one document replaces/removes only its own events).
Dates are ISO YYYY-MM-DD strings — SQLite-friendly and directly comparable; an
event with no calendar date keeps the document's own wording in `date_text`.
"""
from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    start: Mapped[str] = mapped_column(String, nullable=False, default="")  # ISO date
    end: Mapped[str] = mapped_column(String, nullable=False, default="")  # ISO date
    date_text: Mapped[str] = mapped_column(String, nullable=False, default="")
    desc: Mapped[str] = mapped_column(String, nullable=False, default="")
    source: Mapped[str] = mapped_column(String, nullable=False, default="")  # page/section read from
    source_doc: Mapped[str] = mapped_column(String, nullable=False, default="")  # document name
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "start": self.start, "end": self.end,
            "date_text": self.date_text, "desc": self.desc,
            "source": self.source, "source_doc": self.source_doc,
            "confidence": self.confidence,
        }
