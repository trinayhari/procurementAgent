"""Database accessors for extracted timeline events.

Events are scoped to a project (the schedule is built across all of its
documents) and to the source document (re-analysing or deleting a document
replaces/removes only that document's events).
"""
from typing import List

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.timeline_event import TimelineEvent


def replace_for_document(
    db: Session, project_id: str, document_id: str, doc_name: str, events: List[dict]
) -> int:
    """Replace one document's extracted events with a fresh extraction's."""
    db.execute(sa_delete(TimelineEvent).where(TimelineEvent.document_id == document_id))
    for e in events:
        db.add(
            TimelineEvent(
                project_id=project_id,
                document_id=document_id,
                name=e["name"],
                start=e.get("start", ""),
                end=e.get("end", ""),
                date_text=e.get("date_text", ""),
                desc=e.get("desc", ""),
                source=e.get("source", ""),
                source_doc=doc_name,
                confidence=e.get("confidence", 0.5),
            )
        )
    db.commit()
    return len(events)


def list_for_project(db: Session, project_id: str) -> List[dict]:
    rows = db.scalars(
        select(TimelineEvent)
        .where(TimelineEvent.project_id == project_id)
        .order_by(TimelineEvent.start, TimelineEvent.id)
    ).all()
    return [r.to_dict() for r in rows]


def delete_for_documents(db: Session, document_ids: List[str]) -> None:
    """Remove events extracted from documents that are being deleted.

    Commits nothing — callers delete the documents in the same transaction."""
    if not document_ids:
        return
    db.execute(sa_delete(TimelineEvent).where(TimelineEvent.document_id.in_(document_ids)))
