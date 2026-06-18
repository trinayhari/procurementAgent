from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Project(Base):
    """A procurement project — the top-level container the whole app lives in.

    Columns mirror the fields the frontend's project card/table render, including
    the precomputed `*_tone` / `bar_color` styling hints so the seeded prototype
    projects keep their exact look.
    """

    __tablename__ = "projects"

    # Monotonic insertion-order key (assigned by the repo); the UI lists
    # newest-first via ORDER BY seq DESC.
    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    loc: Mapped[str] = mapped_column(String, nullable=False, default="—")
    stage: Mapped[str] = mapped_column(String, nullable=False, default="Plans Review")
    stage_tone: Mapped[str] = mapped_column(String, nullable=False, default="gray")
    value: Mapped[str] = mapped_column(String, nullable=False, default="$0")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppliers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rfqs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk: Mapped[str] = mapped_column(String, nullable=False, default="Low")
    risk_tone: Mapped[str] = mapped_column(String, nullable=False, default="success")
    bar_color: Mapped[str] = mapped_column(String, nullable=False, default="var(--primary)")

    def to_dict(self) -> dict:
        """Shape a row into the camelCase payload the API schemas expect."""
        return {
            "id": self.id,
            "name": self.name,
            "loc": self.loc,
            "stage": self.stage,
            "stageTone": self.stage_tone,
            "value": self.value,
            "progress": self.progress,
            "suppliers": self.suppliers,
            "rfqs": self.rfqs,
            "quotes": self.quotes,
            "risk": self.risk,
            "riskTone": self.risk_tone,
            "barColor": self.bar_color,
        }
