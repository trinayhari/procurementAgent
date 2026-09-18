import re
from typing import List

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import Risk, Stage, Tone

# "$4.2M", "4.2m", "$450,000", "450000", "1.5 B" — an optional currency sign, a
# number with optional thousands separators/decimals, an optional K/M/B suffix.
_VALUE_RE = re.compile(r"^\$?\s*\d{1,3}(,\d{3})*(\.\d+)?\s*[kKmMbB]?$|^\$?\s*\d+(\.\d+)?\s*[kKmMbB]?$")
from app.schemas.dashboard import Activity


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

    # The project id is derived from the name, so a blank one would mint an
    # anonymous "project" row the list can't distinguish. Length-capped: the
    # name is echoed into every event/audit title and breadcrumb.
    name: str = Field(min_length=1, max_length=200)
    loc: str = Field(default="", max_length=200)
    value: str = Field(default="", max_length=50)
    stage: Stage = Stage.plans_review

    @field_validator("name", "loc", "value", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("value")
    @classmethod
    def _value_is_an_amount(cls, v: str) -> str:
        # Free text ("abc") used to be stored and shown as "Value abc". Accept
        # the ways people write a contract value — "$4.2M", "450,000", "1.5 m",
        # "$3.1B" — and nothing else. Blank means "not set".
        if v and not _VALUE_RE.match(v):
            raise ValueError("Est. value must be an amount, e.g. $4.2M or 450,000")
        return v


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
    activity: List[Activity]
