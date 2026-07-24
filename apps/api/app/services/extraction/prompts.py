"""Prompt construction for GPT-4.1 vision BOM extraction.

Kept deliberately simple: ask for the Bill of Materials in the plan type's
categories (for site plans: Water, Sewer, Storm Drain, Erosion Control) and let the
model return it as structured output. The categories come from the `PlanTypeSpec`,
so the prompt stays correct as new plan types are registered — that is the only
thing that varies between plan types.

Two passes (see service.py): `build_user_prompt` reads one sheet; the consolidation
prompts combine the per-sheet results into one Bill of Materials.
"""
import json
from typing import List

from app.services.extraction.registry import PlanTypeSpec

SYSTEM_PROMPT = (
    "You are a construction estimator reading construction plans. Extract the Bill of "
    "Materials — the materials the plans show and how much of each. Only list materials "
    "actually shown on the drawings. Give each item a clear, buyer-ready description and "
    "a quantity with its unit (LF, EA, SY, SF, CY, TON). If a quantity is not shown, set "
    "it to null. Do not invent anything.\n"
    "REPEATED UNITS: sets for multi-unit projects (townhouses, apartment blocks) often "
    "draw ONE typical unit or a partial group of units, while the cover sheet / title "
    "block states how many units the building actually has (e.g. 'UNITS 54-61' = 8). "
    "The BOM is for the WHOLE project: scale typical-unit counts by the number of units "
    "they apply to, state that math in `assumptions` (e.g. '12 per unit × 8 units'), and "
    "keep end-unit vs interior-unit variants separate when the plans distinguish them. "
    "Do NOT collapse eight repeated units into a count for one. Conversely, when the set "
    "draws a single unit or building with no stated repetition, extract as drawn — do "
    "not scale anything."
)


def build_system_prompt(spec: PlanTypeSpec = None) -> str:
    """Base estimator instructions plus the plan-type's own extraction guidance.

    The per-spec `prompt_guidance` and each category's `description`/`examples`
    (defined in plan_types.py) carry the discipline-specific rules — break out every
    fitting, treat `TYP.` items as null, which units to use, etc. They are appended
    here so they actually reach the model; without this the model only sees the
    generic base prompt and silently drops fittings and mis-handles `TYP.` counts.
    """
    if spec is None:
        return SYSTEM_PROMPT
    parts = [SYSTEM_PROMPT]
    if spec.prompt_guidance:
        parts.append(spec.prompt_guidance)
    cat_lines = []
    for c in spec.categories:
        line = f"- `{c.key}` ({c.label}): {c.description}".rstrip()
        if c.examples:
            line += "\n  Example line items: " + "; ".join(c.examples) + "."
        cat_lines.append(line)
    if cat_lines:
        parts.append("Category definitions — what belongs in each:\n" + "\n".join(cat_lines))
    return "\n\n".join(parts)


def _category_keys(spec: PlanTypeSpec) -> str:
    return "; ".join(f"{c.label} = `{c.key}`" for c in spec.categories)


def build_user_prompt(spec: PlanTypeSpec, sheet: str = None) -> str:
    cats = _category_keys(spec)
    if sheet:
        return (
            f"This is one sheet ({sheet}) of a {spec.label}. It may be shown as several "
            "overlapping tiles — treat them as one sheet and do not double-count items in "
            "the overlap.\n"
            f"Give the Bill of Materials shown on this sheet, grouped into these categories "
            f"(use each category's key): {cats}.\n"
            "If this sheet is a symbol LEGEND or general-notes sheet, do NOT list its "
            "symbol definitions as materials (legends define symbols that may not be "
            "used). Materials the NOTES require to be installed ARE part of the BOM — "
            "service equipment with its stated rating ('main service disconnect, min "
            "150A'), code-mandated alarms, and similar: list them with the note as "
            "`source` and, for per-unit requirements, quantity = number of units.\n"
            "Count fixture and device symbols EXHAUSTIVELY, room by room (bedrooms, "
            "baths, halls, stairs, closets, kitchen, carport, exterior porch) — "
            "including fixtures hanging on dashed switch legs.\n"
            "In `sheet_summary`, state what the sheet is (plan / schedule / legend / "
            "notes), how many dwelling units or repeated bays it draws, and — when "
            "symbols are annotated on only SOME of the drawn units (drafters annotate "
            "one typical unit) — which units are annotated. Count symbols from the "
            "annotated units only and record counts per annotated unit in `assumptions`."
        )
    return (
        f"Give the Bill of Materials from this {spec.label}, grouped into these categories "
        f"(use each category's key): {cats}."
    )


def build_text_prompt(spec: PlanTypeSpec, sheets: List[dict]) -> str:
    """One-shot prompt over the embedded text of every sheet (text-layer PDFs).

    `sheets`: [{'sheet': 'Sheet N of M', 'text': ...}]. All sheets fit in one call,
    so there is no per-sheet/consolidation split for the text path.
    """
    cats = _category_keys(spec)
    parts = [
        f"Below is the text extracted from each sheet of a {spec.label}. The set may "
        "also bundle sheets from other disciplines — extract only this plan type's "
        "scope. Give the complete Bill of Materials, grouped into these categories "
        f"(use each category's key): {cats}.\n"
        "MERGE, DO NOT BLINDLY SUM. The SAME physical run or structure usually "
        "appears on several sheets — a pipe is shown on the plan-view sheet AND again "
        "on its profile sheet, and the same callout may be repeated within one sheet. "
        "These are ONE item, not many: count each run/structure ONCE. Use the station "
        "label (e.g. 'STA: 4+71.39 WW LINE A') or the feature name to recognize the "
        "same physical thing across sheets. Only ADD quantities when they are clearly "
        "DIFFERENT runs/segments of the same material (e.g. several distinct pipe "
        "segments that together make up a line). When a plan sheet and a profile sheet "
        "give the same run, prefer the plan-view total and do not add the profile "
        "length on top of it.",
        "",
    ]
    for s in sheets:
        parts.append(f"--- {s['sheet']} ---")
        parts.append(s["text"])
        parts.append("")
    return "\n".join(parts)


TIMELINE_SYSTEM_PROMPT = (
    "You are a construction scheduler reading project documents. Extract the project "
    "timeline: the milestones (point-in-time events like notice to proceed, permit "
    "approval, substantial completion) and phases (activities with a start and end, like "
    "grading, foundations, framing) the document states. Only list events the document "
    "actually gives — do not invent events or dates. Give dates as YYYY-MM-DD when the "
    "document provides a calendar date; when it only gives relative timing (week numbers, "
    "durations, 'X days after NTP'), leave the date fields null and put the document's own "
    "wording in date_text. If the document contains no schedule information, return an "
    "empty events list."
)


def build_timeline_text_prompt(sheets: List[dict]) -> str:
    """One-shot timeline prompt over the embedded text of every page."""
    parts = [
        "Below is the text extracted from each page of a project document. Extract the "
        "project timeline — every milestone and phase with its dates.",
        "",
    ]
    for s in sheets:
        parts.append(f"--- {s['sheet']} ---")
        parts.append(s["text"])
        parts.append("")
    return "\n".join(parts)


def build_timeline_vision_prompt() -> str:
    return (
        "These are the pages of a project document. Extract the project timeline — "
        "every milestone and phase with its dates."
    )


def build_consolidation_system_prompt() -> str:
    return (
        "You are a construction estimator. You are given the materials extracted from each "
        "sheet of one plan set. Combine them into a single Bill of Materials: merge "
        "duplicate materials into one line and sum the quantities of the same material; "
        "keep different sizes and materials separate. The same element often appears on "
        "several sheets (plan + schedule + detail) — that is ONE element, not a sum. "
        "When per-sheet items describe a typical unit of a multi-unit building, the "
        "combined line must cover ALL units (scale and say so in `assumptions`). Prefer "
        "specific plan/schedule callouts over general-notes minimums for the same "
        "element, and never emit a design alternate as a second line item. When two "
        "lines describe the SAME element with conflicting values (e.g. two anchor-bolt "
        "specs, two slab strengths), keep ONE line — the clearest, most specific "
        "callout — and record the conflicting reading in `assumptions` instead of "
        "keeping both. But do NOT over-merge: lines the plans distinguish by circuit, "
        "use, or rating (kitchen small-appliance vs dishwasher vs bathroom GFCI "
        "receptacles; beams by mark) are SEPARATE line items — preserve that "
        "breakdown. Return the final Bill of Materials."
    )


def build_consolidation_user_prompt(
    spec: PlanTypeSpec, per_sheet_items: List[dict], sheet_contexts: List[str] = None
) -> str:
    cats = _category_keys(spec)
    parts = [
        f"Combine these per-sheet materials into one Bill of Materials for a {spec.label}, "
        f"grouped into these categories (use each category's key): {cats}."
    ]
    if sheet_contexts:
        parts.append(
            "Sheet context — use this to scale typical-unit counts to the WHOLE project "
            "(e.g. symbols annotated on 2 of 8 drawn units → multiply per-unit counts by 8):\n"
            + "\n".join(f"- {c}" for c in sheet_contexts)
        )
    parts.append(json.dumps(per_sheet_items, indent=2, default=str))
    return "\n\n".join(parts)
