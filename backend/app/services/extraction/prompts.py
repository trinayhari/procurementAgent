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
    "it to null. Do not invent anything."
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
            f"(use each category's key): {cats}."
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
        f"Below is the text extracted from each sheet of a {spec.label}. Give the "
        f"complete Bill of Materials, grouped into these categories (use each "
        f"category's key): {cats}.\n"
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
        "keep different sizes and materials separate. Return the final Bill of Materials."
    )


def build_consolidation_user_prompt(spec: PlanTypeSpec, per_sheet_items: List[dict]) -> str:
    cats = _category_keys(spec)
    return (
        f"Combine these per-sheet materials into one Bill of Materials for a {spec.label}, "
        f"grouped into these categories (use each category's key): {cats}.\n\n"
        + json.dumps(per_sheet_items, indent=2, default=str)
    )
