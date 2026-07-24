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
    # Some disciplines are drawn graphically with no quantities in the PDF text layer
    # (e.g. erosion control: silt fence / inlet-protection symbols). For these, the
    # text-first pass finds nothing, so we run a targeted vision pass on the sheets
    # whose title text matches `sheet_keywords`. Only triggers when the category is
    # empty after the text pass — text-first stays the default for everything else.
    vision_fallback: bool = False
    sheet_keywords: List[str] = []


class PlanTypeSpec(BaseModel):
    key: str
    label: str  # shown in the document "Type" column and the upload selector
    description: str
    # Extra, plan-type-specific instructions appended to the base prompt.
    prompt_guidance: str = ""
    categories: List[BomCategory]
    # Some plan types carry a text layer that is *unusable* — CAD building sheets
    # render their schedules and dimensioned plans as graphically-positioned text
    # fragments, so reading-order extraction returns scrambled word-salad in which
    # the tabular count/dimension relationships (which is where the quantities live)
    # are destroyed. For these, force the per-sheet VISION path even though a text
    # layer exists, so the model reads the schedules/plans as legible images.
    prefer_vision: bool = False
    # Which drawing disciplines (see sheets.DISCIPLINE_KEYWORDS) this plan type
    # reads. Uploaded sets are often COMBINED (an "approval plan" bundles
    # architectural + MEP + energy sheets), so each plan type extracts only from
    # its own sheets: pages whose title/text matches another discipline are
    # skipped, unclassifiable pages are kept. Empty = read every sheet.
    sheet_disciplines: List[str] = []
    enabled: bool = True  # disabled specs appear greyed-out / "coming soon" in the UI
    # A "slot" plan type — a project holds at most ONE document of this type, so
    # re-uploading replaces the prior one (see documents_repo / the upload route).
    # Site / building / electrical plans are slots; "additional documents" are not.
    singleton: bool = True

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
