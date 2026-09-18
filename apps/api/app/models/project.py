from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Project(Base):
    """A procurement project — the top-level container the whole app lives in.

    Only what the user entered is stored (name, location, estimated value).
    Everything the project card/table shows about *progress* — stage,
    procurement %, suppliers/RFQ/quote counts — is computed from the project's
    own documents, RFQs, quotes and awards (services/metrics.py), never stored.
    """

    __tablename__ = "projects"

    # Tenant boundary — every read/write filters on this explicitly.
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )

    # Monotonic insertion-order key (assigned by the repo); the UI lists
    # newest-first via ORDER BY seq DESC.
    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    loc: Mapped[str] = mapped_column(String, nullable=False, default="—")
    value: Mapped[str] = mapped_column(String, nullable=False, default="$0")
    # Cached geocode of `loc` (supplier search). `geocoded_loc` records the
    # string that was geocoded so a changed `loc` invalidates the cache.
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geocoded_loc: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    def to_dict(self) -> dict:
        """The stored fields, camelCased. Routes merge the computed rollup
        (stage, progress, counts) from services/metrics.py on top."""
        return {
            "id": self.id,
            "name": self.name,
            "loc": self.loc,
            "value": self.value,
            "lat": self.lat,
            "lng": self.lng,
        }
