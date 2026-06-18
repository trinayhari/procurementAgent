from typing import List

from pydantic import BaseModel

from app.schemas.common import Tone


class Milestone(BaseModel):
    name: str
    date: str
    status: str
    desc: str
    tone: Tone
    done: bool = False
    active: bool = False


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
