"""Plan-type registry — the extensibility seam of the extraction pipeline.

Adding support for a NEW kind of plan (building, electrical, mechanical, …) is a
*data* change, not a code change: define a `PlanTypeSpec` with its BOM categories
and register it. The prompt builder (`prompts.py`), the vision call (`vision.py`),
and the orchestrator (`service.py`) are all generic over whatever specs live here.

Each `BomCategory` carries:
  - `key`     stable identifier the model echoes back (see models.ExtractedBom.category)
  - `label`   human group name shown in the UI (e.g. "Water Materials")
  - `tone`    frontend color token (see app.schemas.common.Tone)
  - `description` / `examples` / `typical_units` — guidance fed verbatim into the prompt

So per-discipline extraction quality is tuned by editing the spec below, with no
changes to the calling code.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel


class BomCategory(BaseModel):
    key: str
    label: str
    tone: str  # one of app.schemas.common.Tone
    description: str
    examples: List[str] = []
    typical_units: List[str] = []


class PlanTypeSpec(BaseModel):
    key: str
    label: str  # shown in the document "Type" column and the upload selector
    description: str
    # Extra, plan-type-specific instructions appended to the base prompt.
    prompt_guidance: str = ""
    categories: List[BomCategory]
    enabled: bool = True  # disabled specs appear greyed-out / "coming soon" in the UI

    def category(self, key: str) -> Optional[BomCategory]:
        return next((c for c in self.categories if c.key == key), None)


# --------------------------------------------------------------------- registry
_REGISTRY: Dict[str, PlanTypeSpec] = {}


def register(spec: PlanTypeSpec) -> PlanTypeSpec:
    """Register (or replace) a plan type. Returns the spec for convenient chaining."""
    _REGISTRY[spec.key] = spec
    return spec


def get(key: str) -> Optional[PlanTypeSpec]:
    return _REGISTRY.get(key)


def require(key: str) -> PlanTypeSpec:
    spec = _REGISTRY.get(key)
    if spec is None:
        raise KeyError(f"Unknown plan type '{key}'. Registered: {sorted(_REGISTRY)}")
    return spec


def all_specs() -> List[PlanTypeSpec]:
    return list(_REGISTRY.values())


def default_key() -> str:
    """The plan type selected by default in the UI (first enabled spec)."""
    for spec in _REGISTRY.values():
        if spec.enabled:
            return spec.key
    raise RuntimeError("No enabled plan types registered")
