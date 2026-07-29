"""Database accessors for extracted timeline events.

Events are scoped to an organization, to a project (the schedule is built across
all of its documents), and to the source document (re-analysing or deleting a
document replaces/removes only that document's events).
"""
from typing import Dict, List, Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.timeline_event import TimelineEvent


def _key(name: str) -> str:
    return name.strip().lower()


def replace_for_document(
    db: Session,
    org_id: str,
    project_id: str,
    document_id: str,
    doc_name: str,
    events: List[dict],
) -> int:
    """Replace one document's extracted events with a fresh extraction's.

    User check-offs survive the replacement: an incoming event whose name
    matches an event already marked done in this project (including the ones
    being replaced) comes back done — re-analysing a document must not undo
    confirmed progress."""
    done_at_by_name = {
        _key(name): done_at
        for name, done_at in db.execute(
            select(TimelineEvent.name, TimelineEvent.done_at).where(
                TimelineEvent.organization_id == org_id,
                TimelineEvent.project_id == project_id,
                TimelineEvent.done.is_(True),
            )
        ).all()
    }
    db.execute(
        sa_delete(TimelineEvent).where(
            TimelineEvent.organization_id == org_id,
            TimelineEvent.document_id == document_id,
        )
    )
    for e in events:
        db.add(
            TimelineEvent(
                organization_id=org_id,
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
                done=_key(e["name"]) in done_at_by_name,
                done_at=done_at_by_name.get(_key(e["name"]), ""),
            )
        )
    db.commit()
    return len(events)


def set_done(
    db: Session, org_id: str, event_id: int, done: bool, when: str = ""
) -> Optional[dict]:
    """Check a milestone off (or undo it). Applies to every same-named event in
    the project — the schedule dedupes those into one milestone, so its status
    must be consistent no matter which underlying row represents it."""
    ev = db.get(TimelineEvent, event_id)
    if ev is None or ev.organization_id != org_id:
        return None
    key = _key(ev.name)
    rows = db.scalars(
        select(TimelineEvent).where(
            TimelineEvent.organization_id == org_id,
            TimelineEvent.project_id == ev.project_id,
        )
    ).all()
    updated = 0
    for r in rows:
        if _key(r.name) == key:
            r.done = done
            r.done_at = when if done else ""
            updated += 1
    db.commit()
    return {"projectId": ev.project_id, "name": ev.name, "updated": updated}


def list_for_project(db: Session, org_id: str, project_id: str) -> List[dict]:
    rows = db.scalars(
        select(TimelineEvent)
        .where(
            TimelineEvent.organization_id == org_id,
            TimelineEvent.project_id == project_id,
        )
        .order_by(TimelineEvent.start, TimelineEvent.id)
    ).all()
    return [r.to_dict() for r in rows]


def counts_by_document(db: Session, org_id: str, project_id: str) -> Dict[str, int]:
    """How many events each of the project's documents contributed — lets the
    documents UI point at the Timeline tab when a document changed it."""
    rows = db.execute(
        select(TimelineEvent.document_id, func.count())
        .where(
            TimelineEvent.organization_id == org_id,
            TimelineEvent.project_id == project_id,
        )
        .group_by(TimelineEvent.document_id)
    ).all()
    return {document_id: count for document_id, count in rows}


def count_for_document(db: Session, org_id: str, document_id: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(TimelineEvent)
        .where(
            TimelineEvent.organization_id == org_id,
            TimelineEvent.document_id == document_id,
        )
    ) or 0


def delete_for_documents(db: Session, org_id: str, document_ids: List[str]) -> None:
    """Remove events extracted from documents that are being deleted.

    Commits nothing — callers delete the documents in the same transaction."""
    if not document_ids:
        return
    db.execute(
        sa_delete(TimelineEvent).where(
            TimelineEvent.organization_id == org_id,
            TimelineEvent.document_id.in_(document_ids),
        )
    )
