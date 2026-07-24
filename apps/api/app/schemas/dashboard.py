from typing import List

from pydantic import BaseModel

from app.schemas.common import Tone


class Metric(BaseModel):
    label: str
    value: str
    delta: str
    sub: str = ""
    up: bool = False
    down: bool = False
    ai: bool = False
    risk: bool = False


class Activity(BaseModel):
    icon: str
    tone: Tone
    title: str
    meta: str
    time: str


class Dashboard(BaseModel):
    metrics: List[Metric]
    activity: List[Activity]
