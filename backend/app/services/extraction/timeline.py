"""Timeline extraction orchestrator.

`extract_timeline(path)` reads a project document (construction schedule,
contract, plan set with phasing notes, …) and returns the milestones and phases
it states. Like the BOM path it is TEXT-FIRST: PDFs with an embedded text layer
go to the text model in one cheap call; scans fall back to vision over the
rendered pages. When no OpenAI key is configured it returns no events — there is
deliberately no mock (the timeline shows only real, extracted data).

Dates are normalised here: a value the model returned as start/end that is not a
real YYYY-MM-DD calendar date is demoted to `date_text` so the schedule builder
only ever sees parseable dates. Events with no date information at all are
dropped — they cannot be placed on a schedule.
"""
from datetime import date
from typing import List, Optional

from app.config import settings
from app.services.extraction import vision
from app.services.extraction.models import ExtractedTimelineEvent
from app.services.extraction.pdf import (
    UnsupportedDocument,
    extract_text_pages,
    has_text_layer,
    page_count,
    to_base64_images,
)

# Vision fallback renders whole pages (schedules are legible at page scale, no
# tiling needed); cap pages so a big scanned plan set doesn't explode cost.
_VISION_MAX_PAGES = 12


class TimelineResult:
    """Outcome of a timeline extraction: normalised event dicts plus metadata."""

    def __init__(self, events: List[dict], *, error: Optional[str] = None, summary: Optional[str] = None):
        self.events = events
        self.error = error
        self.summary = summary


def _iso_or_none(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except (ValueError, AttributeError):
        return None


def _normalize(event: ExtractedTimelineEvent) -> Optional[dict]:
    name = (event.name or "").strip()
    if not name:
        return None
    start = _iso_or_none(event.start_date)
    end = _iso_or_none(event.end_date)
    date_text = (event.date_text or "").strip()
    # A non-calendar "date" the model put in the wrong field still carries
    # scheduling meaning — keep it as display text rather than losing it.
    if not date_text:
        raw = event.start_date or event.end_date or ""
        if not start and not end and raw.strip():
            date_text = raw.strip()
    if start and end and end < start:
        start, end = end, start
    # An end without a start is a deadline — a point-in-time milestone.
    if end and not start:
        start, end = end, None
    if not start and not date_text:
        return None  # nothing to place it on a schedule with
    return {
        "name": name,
        "start": start or "",
        "end": end or "",
        "date_text": date_text,
        "desc": (event.description or "").strip(),
        "source": (event.source or "").strip(),
        "confidence": event.confidence,
    }


def extract_timeline(path: str) -> TimelineResult:
    # No key → no events. Timeline data is only ever real extracted data.
    if not vision.is_configured():
        return TimelineResult([], summary="Timeline extraction skipped (no OpenAI key configured).")

    try:
        n_pages = min(page_count(path), settings.vision_max_pages)
    except UnsupportedDocument as exc:
        return TimelineResult([], error=str(exc))
    if n_pages <= 0:
        return TimelineResult([], error="No pages could be rendered from the document")

    try:
        if has_text_layer(path):
            sheets = extract_text_pages(path, settings.vision_max_pages)
            extraction = vision.extract_timeline_text(sheets)
        else:
            images = to_base64_images(path, dpi=settings.vision_dpi, max_pages=min(n_pages, _VISION_MAX_PAGES))
            extraction = vision.extract_timeline_images(images)
    except vision.VisionUnavailable as exc:
        return TimelineResult([], error=str(exc))

    events = [e for e in (_normalize(ev) for ev in extraction.events) if e]
    return TimelineResult(events, summary=(extraction.summary or "").strip() or None)
