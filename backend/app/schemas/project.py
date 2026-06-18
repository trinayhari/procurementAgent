from typing import List

from pydantic import BaseModel

from app.schemas.common import Risk, Stage, Tone


class Project(BaseModel):
    id: str
    name: str
    loc: str
    stage: Stage
    stageTone: Tone
    value: str
    progress: int
    suppliers: int
    rfqs: int
    quotes: int
    risk: Risk
    riskTone: Tone
    barColor: str


class ProjectCreate(BaseModel):
    """Payload for creating a project from the New project modal."""

    name: str
    loc: str = ""
    value: str = ""
    stage: Stage = Stage.plans_review


class OverviewCard(BaseModel):
    label: str
    value: str
    sub: str
    icon: str
    tone: Tone
    ai: bool = False


class Package(BaseModel):
    name: str
    pct: int
    tone: Tone


class ProjectDetail(Project):
    """Full project workspace payload."""

    overviewCards: List[OverviewCard]
    packages: List[Package]
