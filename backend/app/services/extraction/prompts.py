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


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


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
        f"category's key): {cats}. Combine the same material across sheets into one "
        f"line and sum its quantity.",
        "",
    ]
    for s in sheets:
        parts.append(f"--- {s['sheet']} ---")
        parts.append(s["text"])
        parts.append("")
    return "\n".join(parts)


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
