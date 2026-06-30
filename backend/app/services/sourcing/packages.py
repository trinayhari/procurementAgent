"""Buy-package → Google Places search-keyword mapping.

The extractor groups a BOM into the categories defined per plan type in
`extraction/plan_types.py` — site (water/sewer/storm/erosion), building
(concrete/rebar/steel/masonry/framing), and electrical (raceway/conductors/
equipment/devices/lighting/grounding/lowvoltage). Each package here mirrors one
of those categories and fans out into several *specific* search queries rather
than one generic term; the project city/state is appended at search time,
producing queries like "RCP pipe supplier Raleigh NC". Results across a
package's keywords are deduped by place_id in the orchestrator.

The package KEY matches the extraction category key, and `_LABEL_ALIASES` maps
each category's display label (the `group` stored on extracted line items) back
to its key so `_line_items_for_package` can pull the right BOM into an RFQ.
"""
from typing import Dict, List, Optional

# key -> {label, tone (UI), keywords}
PACKAGES: Dict[str, dict] = {
    # ----------------------------------------------------------- SITE / CIVIL
    "water": {
        "label": "Water Utilities",
        "tone": "blue",
        "keywords": [
            "waterworks supplier",
            "PVC water pipe distributor",
            "fire hydrant supplier",
            "water utility pipe supplier",
            "gate valve supplier",
        ],
    },
    "sewer": {
        "label": "Sanitary Sewer",
        "tone": "violet",
        "keywords": [
            "sewer pipe supplier",
            "PVC sewer pipe distributor",
            "precast manhole supplier",
            "sanitary sewer materials supplier",
        ],
    },
    "storm": {
        "label": "Storm Drain",
        "tone": "success",
        "keywords": [
            "RCP pipe supplier",
            "storm drain pipe supplier",
            "precast box culvert supplier",
            "drainage structure supplier",
            "catch basin inlet supplier",
        ],
    },
    "erosion": {
        "label": "Erosion Control",
        "tone": "warn",
        "keywords": [
            "erosion control supplier",
            "silt fence supplier",
            "geotextile distributor",
            "landscape supply yard",
        ],
    },
    # --------------------------------------------------- BUILDING / STRUCTURAL
    "concrete": {
        "label": "Cast-in-Place Concrete",
        "tone": "gray",
        "keywords": [
            "ready mix concrete supplier",
            "concrete batch plant",
            "ready-mix concrete delivery",
        ],
    },
    "rebar": {
        "label": "Reinforcing Steel",
        "tone": "warn",
        "keywords": [
            "rebar supplier",
            "rebar fabricator",
            "reinforcing steel supplier",
            "welded wire mesh supplier",
        ],
    },
    "steel": {
        "label": "Structural Steel",
        "tone": "blue",
        "keywords": [
            "structural steel fabricator",
            "structural steel supplier",
            "steel joist supplier",
            "metal deck supplier",
        ],
    },
    "masonry": {
        "label": "Masonry",
        "tone": "violet",
        "keywords": [
            "masonry supply",
            "concrete block CMU supplier",
            "brick supplier",
            "mortar and grout supplier",
        ],
    },
    "framing": {
        "label": "Wood & Framing",
        "tone": "success",
        "keywords": [
            "lumber supplier",
            "framing lumber yard",
            "engineered lumber supplier",
            "metal stud framing supplier",
        ],
    },
    # ----------------------------------------------------------- ELECTRICAL
    "raceway": {
        "label": "Conduit & Raceway",
        "tone": "warn",
        "keywords": [
            "electrical supply house",
            "conduit supplier",
            "EMT conduit distributor",
            "electrical raceway supplier",
        ],
    },
    "conductors": {
        "label": "Wire & Cable",
        "tone": "blue",
        "keywords": [
            "electrical wire and cable supplier",
            "building wire distributor",
            "electrical cable supplier",
        ],
    },
    "equipment": {
        "label": "Panels & Distribution",
        "tone": "violet",
        "keywords": [
            "electrical distributor",
            "panelboard supplier",
            "switchgear supplier",
            "electrical equipment supplier",
        ],
    },
    "devices": {
        "label": "Devices & Rough-in",
        "tone": "gray",
        "keywords": [
            "electrical supply house",
            "wiring device distributor",
            "electrical box supplier",
        ],
    },
    "lighting": {
        "label": "Lighting Fixtures",
        "tone": "success",
        "keywords": [
            "commercial lighting distributor",
            "LED lighting fixture supplier",
            "lighting supply house",
        ],
    },
    "grounding": {
        "label": "Grounding & Bonding",
        "tone": "danger",
        "keywords": [
            "electrical grounding supplier",
            "ground rod supplier",
            "electrical supply house",
        ],
    },
    "lowvoltage": {
        "label": "Low-Voltage & Fire Alarm",
        "tone": "ai",
        "keywords": [
            "fire alarm equipment supplier",
            "low voltage supply",
            "structured cabling distributor",
            "security systems distributor",
        ],
    },
}

# Some line-item group labels (from the extractor / seed) don't match the keys
# 1:1; normalise common labels back to a package key.
_LABEL_ALIASES = {
    # site / civil
    "water materials": "water",
    "water utilities": "water",
    "sewer materials": "sewer",
    "sanitary sewer": "sewer",
    "storm materials": "storm",
    "storm drain": "storm",
    "storm drain materials": "storm",
    "erosion control": "erosion",
    "erosion control materials": "erosion",
    # building / structural
    "cast-in-place concrete": "concrete",
    "reinforcing steel": "rebar",
    "structural steel & metals": "steel",
    "structural steel": "steel",
    "masonry materials": "masonry",
    "masonry": "masonry",
    "wood & light-gauge framing": "framing",
    "wood & framing": "framing",
    # electrical
    "conduit & raceway": "raceway",
    "wire & cable": "conductors",
    "panels & distribution equipment": "equipment",
    "panels & distribution": "equipment",
    "devices, boxes & rough-in": "devices",
    "devices & rough-in": "devices",
    "lighting fixtures": "lighting",
    "grounding & bonding": "grounding",
    "low-voltage & fire alarm": "lowvoltage",
}


def all_keys() -> List[str]:
    return list(PACKAGES.keys())


def keywords_for(category_key: str) -> List[str]:
    pkg = PACKAGES.get(category_key)
    return list(pkg["keywords"]) if pkg else []


def label_for(category_key: str) -> str:
    pkg = PACKAGES.get(category_key)
    return pkg["label"] if pkg else category_key.title()


def tone_for(category_key: str) -> str:
    pkg = PACKAGES.get(category_key)
    return pkg["tone"] if pkg else "gray"


def category_for_label(label: str) -> Optional[str]:
    """Best-effort reverse lookup from a display label to a package key."""
    if not label:
        return None
    norm = label.strip().lower()
    if norm in PACKAGES:
        return norm
    return _LABEL_ALIASES.get(norm)


def is_valid(category_key: str) -> bool:
    return category_key in PACKAGES
