"""Discipline classification of plan-set sheets.

Uploaded sets are frequently COMBINED plan sets — a residential "approval plan"
bundles architectural, structural, MEP, plumbing, and energy-code sheets in one
PDF. Extracting a discipline's BOM from the whole set both wastes vision calls
and hurts accuracy (the model reads 'this is an architectural set' and returns
nothing for electrical, or pads the building BOM with plumbing fixtures).

Each page is scored against per-discipline keyword lists using its embedded
text (title block + notes). Keywords come in two tiers: STRONG title-grade
words (a sheet that says 'PLUMBING' or 'MEP' is that discipline's sheet) and
weak content words (JOIST, DUCT, PEX) that accumulate evidence. Two structural
quirks of real sets are handled explicitly:

  • MEP sheets draw the electrical/plumbing/HVAC scope ON TOP of the floor
    plan, so framing words from the background outscore any single MEP
    discipline. The three MEP disciplines are therefore compared as a FAMILY
    against the base disciplines (structural/civil) before picking a primary.
  • A sheet titled 'MEP' carries all three disciplines at once, so it counts
    as a match for an electrical (or plumbing/mechanical) plan type even when
    its primary lands elsewhere in the family.

Selection is conservative in both directions: a page is only excluded when it
positively classifies as a DIFFERENT discipline; unknown pages are kept for
vision passes (an image-only foundation sheet must not be dropped just because
it has no text layer); and if nothing matches the spec, the caller falls back
to every page. Keyword lists include common CAD-drafting misspellings seen in
real sets ("ELETRICAL", "STRUCUTRAL") — title blocks are hand-typed.
"""
import re
from typing import Dict, List, Optional

from app.services.extraction.registry import PlanTypeSpec

# strong: unambiguous discipline/title words — weight 4 per occurrence.
# weak:   content words — weight 1 (2 for multi-word phrases, stronger signal).
# NOTE: bare "PANEL" is deliberately absent ("BRACE WALL PANEL" on framing
# sheets) — only qualified forms count for electrical.
DISCIPLINE_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    "civil": {
        "strong": ["SITE PLAN", "GRADING", "EROSION", "SWPPP", "PLAT",
                   "PLAN & PROFILE", "PLAN AND PROFILE"],
        "weak": ["DRAINAGE", "UTILITY PLAN", "STORM", "WATERLINE", "WATER LINE",
                 "SANITARY SEWER", "SEWER MAIN", "PAVING", "SUBDIVISION", "CIVIL"],
    },
    "structural": {
        # Architectural + structural — the building_plan scope.
        "strong": ["STRUCTURAL", "STRUCUTRAL", "FRAMING", "FOUNDATION"],
        "weak": ["FLOOR PLAN", "ROOF PLAN", "ELEVATION", "CROSS SECTION",
                 "WALL SECTION", "FOOTING", "SHEAR WALL", "BRACE WALL", "TRUSS",
                 "JOIST", "RAFTER", "STUD", "LVL", "SHEATHING", "COVER SHEET",
                 "DRAWING INDEX"],
    },
    "electrical": {
        "strong": ["ELECTRICAL", "ELETRICAL", "MEP", "LUMINAIRE", "PANELBOARD",
                   "ONE-LINE DIAGRAM", "ONE LINE DIAGRAM"],
        "weak": ["LIGHTING", "POWER PLAN", "RISER DIAGRAM", "CIRCUIT",
                 "RECEPTACLE", "BREAKER", "CONDUIT", "PANEL SCHEDULE"],
    },
    "plumbing": {
        "strong": ["PLUMBING", "MEP", "ISOMETRIC"],
        "weak": ["SANITARY RISER", "FIXTURE UNITS", "CLEANOUT", "BACKFLOW",
                 "WATER HEATER", "PEX", "HOSE BIB"],
    },
    "mechanical": {
        "strong": ["MECHANICAL", "MEP"],
        "weak": ["HVAC", "DUCTWORK", "DUCT", "CONDENSATE", "SEER",
                 "AIR HANDLER", "THERMOSTAT"],
    },
    "energy": {
        "strong": ["ENERGY CODE", "ENERGY COMPLIANCE"],
        "weak": ["IECC", "R-VALUE", "INSULATION SCHEDULE"],
    },
}

# The disciplines drawn as overlays on MEP sheets (see module docstring).
MEP_FAMILY = ("electrical", "plumbing", "mechanical")
# Base disciplines whose words also appear as MEP-sheet background.
BASE_FAMILY = ("structural", "civil")


def _score(text_upper: str, tiers: Dict[str, List[str]]) -> int:
    score = 0
    for kw in tiers["strong"]:
        score += text_upper.count(kw) * 4
    for kw in tiers["weak"]:
        score += text_upper.count(kw) * (2 if " " in kw else 1)
    return score


def _scores(text: str) -> Dict[str, int]:
    up = text.upper()
    return {d: _score(up, tiers) for d, tiers in DISCIPLINE_KEYWORDS.items()}


def classify_page(text: str) -> Optional[str]:
    """Primary discipline of one page's text, or None when unclassifiable."""
    scores = _scores(text)
    if not any(scores.values()):
        return None
    mep_total = sum(scores[d] for d in MEP_FAMILY)
    base_total = sum(scores[d] for d in BASE_FAMILY)
    if mep_total > base_total:
        family = MEP_FAMILY
    elif base_total > 0:
        family = BASE_FAMILY  # ties go to base: floor plans legitimately carry HVAC notes
    else:
        family = tuple(scores)  # only energy/admin signal left
    return max(family, key=lambda d: scores[d])


def _is_mep_sheet(text: str) -> bool:
    """A sheet literally titled 'MEP' carries all three MEP disciplines."""
    return re.search(r"\bMEP\b", text.upper()) is not None


class SheetSelection:
    """Which sheets of the set a plan type should read.

    `text_pages`    — extract_text_pages entries to feed the text-first prompt.
    `vision_indices`— 0-based page indices for vision passes (matched + unknown).
    `matched_indices` — 0-based indices that positively matched the spec's
                        disciplines (preferred for targeted vision escalation).
    `note`          — short human-readable description for summaries/logs.
    """

    def __init__(self, text_pages, vision_indices, matched_indices, note):
        self.text_pages = text_pages
        self.vision_indices = vision_indices
        self.matched_indices = matched_indices
        self.note = note


def select_sheets(spec: PlanTypeSpec, pages: List[dict], total_pages: int) -> SheetSelection:
    """Partition the set's pages for `spec`.

    `pages` is extract_text_pages() output (text-bearing pages only, each with
    an `index`). Pages absent from `pages` (no embedded text) are UNKNOWN.
    With no `sheet_disciplines` on the spec, everything is selected unchanged.
    """
    all_indices = list(range(total_pages))
    if not spec.sheet_disciplines:
        return SheetSelection(pages, all_indices, [], "")

    wants_mep = any(d in MEP_FAMILY for d in spec.sheet_disciplines)
    primary: Dict[int, Optional[str]] = {}
    matched: List[int] = []
    for p in pages:
        primary[p["index"]] = classify_page(p["text"])
        if primary[p["index"]] in spec.sheet_disciplines or (
            wants_mep and _is_mep_sheet(p["text"])
        ):
            matched.append(p["index"])

    unknown = [i for i in all_indices if primary.get(i) is None]  # no text or no hits
    excluded = [i for i in all_indices if i not in matched and i not in unknown]

    # Nothing positively matched → classification has no signal for this spec on
    # this set; fall back to every page rather than guessing wrong.
    if not matched:
        return SheetSelection(pages, all_indices, [], "")

    keep = set(matched) | set(unknown)
    text_pages = [p for p in pages if p["index"] in keep]
    note = (
        f"{len(matched)} {'/'.join(spec.sheet_disciplines)} sheet(s) of {total_pages}"
        + (f", {len(excluded)} other-discipline skipped" if excluded else "")
    )
    return SheetSelection(text_pages, sorted(keep), sorted(matched), note)
