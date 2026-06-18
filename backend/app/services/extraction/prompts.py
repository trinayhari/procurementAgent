"""Prompt construction for GPT-4.1 vision BOM extraction.

The prompt is assembled from a `PlanTypeSpec` so it is automatically correct for
whatever plan types are registered — the categories, their descriptions, example
items, and units are all injected from the spec. This is what makes the system
modular: a new plan type ships a new prompt for free.

A complete takeoff needs TWO passes (see service.py):
  1. Per-sheet extraction — `build_system_prompt` + `build_user_prompt(spec, sheet=...)`
     read each sheet in isolation so nothing is missed (pipe lengths on profiles,
     structure counts on plan views, items in schedules).
  2. Consolidation — `build_consolidation_system_prompt` + `build_consolidation_user_prompt`
     merge the per-sheet results into one deduplicated BOM, since the same physical
     run/structure appears on multiple sheets and must be counted exactly once.

The prompt is assembled from a `PlanTypeSpec` so it is automatically correct for
whatever plan types are registered — making the system modular.
"""
import json
from typing import List

from app.services.extraction.registry import PlanTypeSpec

SYSTEM_PROMPT = """\
You are a senior construction estimator and quantity surveyor with 20+ years \
reading civil and building construction drawings. You extract accurate Bills of \
Materials (BOM) from plan sheets for procurement.

You are given one or more rendered pages from a single plan set. Read them like an \
estimator doing a material takeoff:
- Inspect the drawing itself, plus every legend, schedule, table, callout bubble, \
keynote, and general note. Quantities are spread across all of these.
- Identify each distinct material and its quantity. Combine identical specs that \
appear as multiple runs; keep different sizes/classes/materials separate.
- Capture the full descriptive spec a buyer needs to source the item: size, \
material, class/schedule/rating, and type (e.g. '12" DI Pipe, Class 350', not just \
'pipe').

Hard rules:
- Extract ONLY what the drawings actually show. Never fabricate quantities or items.
- If a quantity is not shown and cannot be reasonably derived, set quantity to null \
and explain in `assumptions`. Do the same for any estimated counts.
- Use standard construction units: LF (linear feet), EA (each), SY (square yard), \
SF (square foot), CY (cubic yard), TON. Pick the unit the plan uses.
- Assign every item to exactly one of the provided category keys. Anything that \
fits no category goes in `unmatched_notes` (do not force-fit it).
- Set a calibrated `confidence` (0-1) per item: high when read directly from a \
schedule/callout, lower when inferred or partially legible.

Return only the structured object requested — no prose outside it."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def _category_catalog(spec: PlanTypeSpec) -> List[str]:
    lines: List[str] = []
    for c in spec.categories:
        lines.append(f"### {c.label}  (key: `{c.key}`)")
        lines.append(c.description)
        if c.examples:
            lines.append("Example items: " + "; ".join(c.examples))
        if c.typical_units:
            lines.append("Typical units: " + ", ".join(c.typical_units))
        lines.append("")
    return lines


def build_user_prompt(spec: PlanTypeSpec, sheet: str = None) -> str:
    """User prompt for one extraction call.

    `sheet` (e.g. "Sheet 16 of 26") frames a single-sheet pass: the model is told
    to read just this sheet and to set every item's `source` to the sheet label so
    the consolidation pass can reason about provenance.
    """
    lines = [
        f"PLAN TYPE: {spec.label} (key: `{spec.key}`)",
        spec.description,
        "",
    ]
    if sheet:
        lines += [
            f"You are looking at a SINGLE sheet ({sheet}) from a larger plan set. It may "
            "be supplied as several overlapping TILES (zoomed-in crops of the same sheet) "
            "so small callout text is legible — treat all attached images as ONE sheet and "
            "do NOT double-count an item that appears in the overlap between tiles.",
            "Extract every BOM item visible on THIS sheet — from the drawing, callouts, "
            "schedules, tables, and notes. Count structures (manholes, valves, hydrants, "
            "inlets, catch basins, fittings) shown in plan view, read pipe lengths from "
            "profiles, stationing, and length labels, and read fitting callouts and bend "
            "angles wherever they are labeled.",
            f"Set each item's `source` to \"{sheet}\". Set `feature` to the label of the "
            "specific run or structure it belongs to when one is shown (e.g. 'Waterline A', "
            "'WW Line B', 'Storm Line A', 'MH-3') — this lets the same feature seen on "
            "multiple sheets be reconciled later. If this sheet is a cover, index, detail, "
            "or general-notes sheet with no quantifiable materials, return an empty `boms` list.",
            "",
        ]
    lines += [
        "Extract a Bill of Materials for EACH applicable category below. "
        "Use the exact category KEY shown in backticks:",
        "",
    ]
    lines += _category_catalog(spec)

    if spec.prompt_guidance:
        lines += ["PLAN-TYPE GUIDANCE:", spec.prompt_guidance, ""]

    lines.append(
        "Group items by the category keys above, omit categories with no items, and "
        "list anything out-of-scope in `unmatched_notes`."
    )
    return "\n".join(lines)


# ----------------------------------------------------------- consolidation pass
CONSOLIDATION_SYSTEM_PROMPT = """\
You are a senior construction estimator consolidating a material takeoff. You are \
given BOM line items that were extracted SHEET-BY-SHEET from one plan set, each \
tagged with the source sheet it came from. Your job is to produce the single, \
final, deduplicated Bill of Materials for the whole project.

Each input item carries a `feature` (the run/structure it belongs to, e.g. \
'WW Line B') and a `source` (the sheet it came from). Use these to reconcile.

Critical rules:
- COUNT EACH PHYSICAL FEATURE EXACTLY ONCE. The same `feature` (e.g. 'WW Line B') \
appears on several sheets — plan view, profile, AND schedule. These are the SAME \
physical run: report its length ONCE (do not add the sheets together). Match by \
`feature` + size + material.
- SUM ACROSS DIFFERENT FEATURES of the same spec. Distinct features ('WW Line A', \
'WW Line B', 'WW Line C') of the same pipe spec are different physical runs → their \
lengths ADD UP into one line item whose quantity is the total. This is how you get \
the total LF of, say, 8" PVC SDR-35 sewer main for the project.
- When the same item shows different quantities on different sheets, prefer the \
most authoritative source in this order: quantity/material schedule or takeoff \
table > profile sheet (for pipe lengths) > plan-view callout. Note the chosen \
basis in `assumptions`.
- DO sum quantities that represent genuinely DISTINCT items (e.g. three different \
sewer line segments A, B, C are three quantities of the same pipe spec → combine \
into ONE line item whose quantity is the SUM of the segment lengths, since they are \
the same material).
- Merge identical specifications into one line item with a combined quantity; keep \
different sizes, classes, and materials as separate line items.
- PRESERVE QUANTITIES. Never discard a numeric quantity that any sheet provided. \
When segments combine, the result's quantity is their total. Only set quantity to \
null when NO sheet gave a number for that item — and then put the UNIT in `unit` and \
say so in `assumptions`. Do not output a unit with a null quantity unless the count \
is genuinely unknown.
- INCLUDE ONLY PROCURABLE MATERIALS AND STRUCTURES — things a buyer orders. EXCLUDE \
construction-detail and installation-method artifacts that get pulled off standard \
detail sheets, e.g. 'pipe embedment', 'bedding', 'trench repair', 'typical bend', \
'joint type', 'pavement section', 'thrust block', and generic 'typical'/'standard' \
detail titles. These are how-to-build details, not line items. When in doubt, a real \
line item has (or could have) a project quantity; a detail does not.
- Preserve the precise, buyer-ready description (size, material, class/schedule).
- Keep a calibrated `confidence` per consolidated item.

Return only the structured consolidated BOM."""


def build_consolidation_system_prompt() -> str:
    return CONSOLIDATION_SYSTEM_PROMPT


def build_consolidation_user_prompt(spec: PlanTypeSpec, per_sheet_items: List[dict]) -> str:
    """`per_sheet_items`: flat list of {category, name, quantity, unit, spec, source, confidence}."""
    lines = [
        f"PLAN TYPE: {spec.label} (key: `{spec.key}`)",
        "",
        "Valid category keys (assign every consolidated item to one of these):",
    ]
    lines += [f"  - `{c.key}` = {c.label}" for c in spec.categories]
    lines += [
        "",
        "Below are all line items extracted from the individual sheets, as JSON. "
        "Consolidate them into the final project BOM per the rules, merging duplicates "
        "across sheets and summing only genuinely distinct quantities:",
        "",
        json.dumps(per_sheet_items, indent=2, default=str),
    ]
    return "\n".join(lines)
