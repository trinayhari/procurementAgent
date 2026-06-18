"""Buy-package → Google Places search-keyword mapping.

The extractor groups a BOM into the categories below (water/sewer/storm/erosion).
Each package fans out into several *specific* search queries rather than one
generic term; the project city/state is appended at search time, producing
queries like "RCP pipe supplier Raleigh NC". Results across a package's keywords
are deduped by place_id in the orchestrator.
"""
from typing import Dict, List, Optional

# key -> {label, tone (UI), keywords}
PACKAGES: Dict[str, dict] = {
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
}

# Some line-item group labels (from the extractor / seed) don't match the keys
# 1:1; normalise common labels back to a package key.
_LABEL_ALIASES = {
    "water materials": "water",
    "water utilities": "water",
    "sewer materials": "sewer",
    "sanitary sewer": "sewer",
    "storm materials": "storm",
    "storm drain": "storm",
    "erosion control": "erosion",
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
