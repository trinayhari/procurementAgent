from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import Tone


class Milestone(BaseModel):
    # Underlying timeline_events row id — present for extracted milestones so
    # they can be checked off; None for seeded demo milestones.
    id: Optional[int] = None
    name: str
    date: str
    status: str
    desc: str
    tone: Tone
    done: bool = False
    active: bool = False
    # True when project documents disagree on this event's dates; desc lists
    # every claimed date and its source document.
    conflict: bool = False


class MilestoneDoneUpdate(BaseModel):
    """Body for checking a milestone off (or undoing it)."""

    done: bool


class MilestoneDoneResult(BaseModel):
    updated: int  # events updated (every same-named event in the project)


class GanttBar(BaseModel):
    name: str
    start: int
    len: int
    tone: Tone
    label: str
    warn: bool = False


class Timeline(BaseModel):
    milestones: List[Milestone]
    gantt: List[GanttBar]
    ganttCols: List[str]
