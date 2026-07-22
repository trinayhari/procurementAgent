"""Extraction orchestrator.

`extract_document(path, plan_type)` is the one entry point the API uses. It is
SHEET-AWARE and TEXT-FIRST:
  • Sheets are classified by discipline first (see sheets.py) — combined sets
    (arch + MEP + energy in one PDF) only feed each plan type its own sheets.
  • Vector CAD PDFs carry an embedded text layer with every callout, quantity, and
    schedule as exact text. When present, we send that text to a regular (non-vision)
    model in ONE call — fast, cheap, and more accurate than reading pixels. When the
    text pass comes back (near-)empty — the discipline's content is symbols, not
    text — it ESCALATES to vision on the discipline's matched sheets.
  • Scanned PDFs / image uploads have no text layer, so they fall back to the vision
    pipeline: each sheet is rasterised to high-DPI tiles, read per-sheet in parallel,
    then a consolidation pass merges the per-sheet items into one deduplicated BOM.

Either way the category-keyed result is mapped onto the frontend's BOM groups
(`group`, `count`, `tone`, `items[{n, q}]`) via `_to_groups` — the only place
presentation is derived. A clearly-flagged mock runs when no key/SDK is present.
"""
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

import os

from app.config import settings
from app.services.extraction import registry, sheets, vision
from app.services.extraction.models import ExtractedBom, ExtractedItem, VisionExtraction
from app.services.extraction.pdf import (
    PDF_EXTS,
    UnsupportedDocument,
    extract_text_pages,
    page_count,
    to_page_tiles,
)


class ExtractionResult:
    """Outcome of an extraction: BOM groups plus metadata for the document record."""

    def __init__(
        self,
        groups: List[dict],
        total_items: int,
        *,
        mocked: bool = False,
        error: Optional[str] = None,
        summary: Optional[str] = None,
    ):
        self.groups = groups
        self.total_items = total_items
        self.mocked = mocked
        self.error = error
        self.summary = summary


def _quantity_display(item: ExtractedItem) -> str:
    if item.quantity is None:
        return "—"  # honest: unknown quantity, not a bare unit
    qty = item.quantity
    num = f"{int(qty):,}" if float(qty).is_integer() else f"{qty:,.2f}"
    return f"{num} {item.unit}".strip() if item.unit else num


def _to_groups(spec: registry.PlanTypeSpec, extraction: VisionExtraction) -> Tuple[List[dict], int]:
    """Map category-keyed BOMs onto ordered frontend groups, respecting spec order."""
    by_key = {b.category: b for b in extraction.boms}
    groups: List[dict] = []
    total = 0
    for cat in spec.categories:  # spec order → stable UI order
        bom = by_key.get(cat.key)
        if not bom or not bom.items:
            continue
        items = [{"n": it.name, "q": _quantity_display(it)} for it in bom.items]
        groups.append({"group": cat.label, "count": len(items), "tone": cat.tone, "items": items})
        total += len(items)
    return groups, total


def _extract_sheets(
    spec: registry.PlanTypeSpec, path: str, indices: List[int], total: int, dense: bool = False
) -> Tuple[List[dict], List[str], int, int]:
    """Run the per-sheet extraction pass over the given sheets, in parallel.

    Each sheet is rendered as high-DPI tiles (so small fitting callouts are legible)
    and sent as one call. `dense` uses the finer tile grid for targeted passes over
    a few sheets, where small plan symbols must stay countable. Returns (flat
    per-sheet items with provenance, per-sheet context summaries, sheets_ok,
    sheets_failed). A sheet that errors is skipped rather than failing the document.
    """
    cols = settings.vision_dense_tile_cols if dense else settings.vision_tile_cols
    rows = settings.vision_dense_tile_rows if dense else settings.vision_tile_rows

    def one(idx):
        label = f"Sheet {idx + 1} of {total}"
        tiles = to_page_tiles(
            path, idx,
            dpi=settings.vision_tile_dpi,
            cols=cols,
            rows=rows,
            overlap=settings.vision_tile_overlap,
        )
        extraction = vision.extract(spec, tiles, sheet=label)
        out = []
        for bom in extraction.boms:
            for it in bom.items:
                out.append({
                    "category": bom.category,
                    "name": it.name,
                    "quantity": it.quantity,
                    "unit": it.unit,
                    "spec": it.spec,
                    "feature": it.feature,
                    "source": it.source or label,
                    "confidence": it.confidence,
                })
        summary = (extraction.sheet_summary or "").strip()
        return out, (f"{label}: {summary}" if summary else None)

    items: List[dict] = []
    contexts: List[str] = []
    ok = failed = 0
    workers = max(1, min(settings.vision_max_workers, len(indices)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(_safe(one), indices):
            if result is None:
                failed += 1
            else:
                ok += 1
                items.extend(result[0])
                if result[1]:
                    contexts.append(result[1])
    return items, contexts, ok, failed


def _safe(fn):
    """Wrap a sheet worker so one bad sheet returns None instead of raising."""
    def wrapped(arg):
        try:
            return fn(arg)
        except Exception:
            return None
    return wrapped


def _vision_topup(spec, path, text_pages, final) -> None:
    """Fill `final` in place for graphical categories the text pass left empty.

    For each category flagged `vision_fallback` that has no items yet, find the
    sheets whose text title matches its `sheet_keywords`, vision-extract them, and
    append that category's items (deduped by name). Text-first stays primary — this
    only runs for the gap, and only on the matching sheet(s).
    """
    present = {b.category for b in final.boms if b.items}
    gaps = [c for c in spec.categories if c.vision_fallback and c.key not in present]
    if not gaps:
        return

    for cat in gaps:
        # Sheets whose embedded text mentions this discipline's plan title.
        targets = [
            s["index"]
            for s in text_pages
            if any(kw.upper() in s["text"].upper() for kw in cat.sheet_keywords)
        ][:3]  # bound cost
        items, seen = [], set()
        for idx in targets:
            try:
                # Dense grid: top-up sheets are symbol-counting sheets (lighting,
                # erosion BMPs) and the pass reads at most 3 of them.
                tiles = to_page_tiles(
                    path, idx,
                    dpi=settings.vision_tile_dpi,
                    cols=settings.vision_dense_tile_cols,
                    rows=settings.vision_dense_tile_rows,
                    overlap=settings.vision_tile_overlap,
                )
                ex = vision.extract(spec, tiles, sheet=f"Sheet {idx + 1}")
            except Exception:
                # Best-effort enrichment only — a failed top-up (vision error,
                # tiling/render failure) must never discard the text-pass BOM
                # that was already extracted. Skip this sheet and move on.
                continue
            for bom in ex.boms:
                if bom.category != cat.key:
                    continue
                for it in bom.items:
                    if it.name.lower() not in seen:
                        seen.add(it.name.lower())
                        items.append(it)
        if items:
            final.boms.append(ExtractedBom(category=cat.key, items=items))


def extract_document(path: str, plan_type: str) -> ExtractionResult:
    spec = registry.require(plan_type)

    # Count pages; unsupported types (DWG/ZIP) can't go through vision.
    try:
        n_pages = min(page_count(path), settings.vision_max_pages)
    except UnsupportedDocument as exc:
        return ExtractionResult([], 0, error=str(exc))
    if n_pages <= 0:
        return ExtractionResult([], 0, error="No pages could be rendered from the document")

    # No key / SDK → return a representative mock so the UX keeps working locally.
    if not vision.is_configured():
        groups, total = _to_groups(spec, _mock_extraction(spec))
        return ExtractionResult(
            groups, total, mocked=True,
            summary="Mock extraction (set PROCUREAI_OPENAI_API_KEY for live GPT-4.1 extraction).",
        )

    # Classify the set's sheets and keep the ones this discipline reads — uploaded
    # sets are often combined (arch + MEP + energy in one "approval plan" PDF).
    is_pdf = os.path.splitext(path)[1].lower() in PDF_EXTS
    pages = extract_text_pages(path, settings.vision_max_pages) if is_pdf else []
    sel = sheets.select_sheets(spec, pages, n_pages)

    # Text-first — vector CAD PDFs carry the BOM as exact text; one cheap text call
    # over the relevant sheets. Skipped for plan types whose text layer is scrambled
    # (prefer_vision): there the schedules/plans are only legible as rendered images.
    escalation_note = None
    text_chars = sum(len(p["text"]) for p in sel.text_pages)
    if text_chars >= 500 and not spec.prefer_vision:
        try:
            final = vision.extract_text(spec, sel.text_pages)
        except vision.VisionUnavailable as exc:
            return ExtractionResult([], 0, error=str(exc))
        found = sum(len(b.items) for b in final.boms)
        if found >= settings.text_pass_min_items:
            # Targeted vision top-up for graphical disciplines (e.g. erosion control,
            # lighting) that carry no quantities in the text layer. Keyword-match
            # against ALL text pages, not just the selected ones.
            _vision_topup(spec, path, pages, final)
            groups, total = _to_groups(spec, final)
            summary = (final.sheet_summary or "").strip() or f"{len(sel.text_pages)} sheet(s) · text layer"
            if sel.note:
                summary = f"{summary} · {sel.note}"
            return ExtractionResult(groups, total, summary=summary)
        # The discipline's content is drawn, not written (symbols on MEP/plan
        # sheets) — the text pass can't see it. Escalate to vision on the sheets
        # that matched this discipline instead of returning a near-empty BOM.
        escalation_note = f"text layer had {found} item(s); read sheets as images"

    # Vision path: scanned PDFs / images, prefer_vision plan types, and text-pass
    # escalation. Targeted escalation reads only the positively-matched sheets;
    # otherwise read every selected sheet (incl. unclassifiable image-only pages).
    if escalation_note and sel.matched_indices:
        indices = sel.matched_indices
    else:
        indices = sel.vision_indices

    # Pass 1 — per-sheet extraction (each sheet tiled). Targeted escalation over a
    # few sheets uses the dense tile grid so small plan symbols stay countable.
    dense = bool(escalation_note) and len(indices) <= 6
    try:
        per_sheet, contexts, ok, failed = _extract_sheets(spec, path, indices, n_pages, dense=dense)
    except vision.VisionUnavailable as exc:
        return ExtractionResult([], 0, error=str(exc))
    if ok == 0:
        return ExtractionResult([], 0, error="Every sheet failed to extract")

    # Pass 2 — consolidate into one deduplicated BOM. The per-sheet context
    # summaries let the merge scale typical-unit counts to the whole project.
    if per_sheet:
        try:
            final = vision.consolidate(spec, per_sheet, contexts)
        except vision.VisionUnavailable:
            final = _fallback_consolidation(spec, per_sheet)  # union, no merge
    else:
        final = VisionExtraction(plan_type=spec.key, boms=[])

    groups, total = _to_groups(spec, final)
    summary = (final.sheet_summary or "").strip() or None
    note = f"{ok} sheet(s) read" + (f", {failed} failed" if failed else "")
    for extra in (sel.note, escalation_note):
        if extra:
            note = f"{note} · {extra}"
    summary = f"{summary} ({note})" if summary else note
    return ExtractionResult(groups, total, summary=summary)


def _fallback_consolidation(spec: registry.PlanTypeSpec, per_sheet: List[dict]) -> VisionExtraction:
    """If the consolidation call fails, return the raw per-sheet union (un-merged)
    so the user still sees everything found — duplicates included, flagged."""
    by_cat = {}
    for it in per_sheet:
        by_cat.setdefault(it["category"], []).append(
            ExtractedItem(
                name=it["name"], quantity=it.get("quantity"), unit=it.get("unit"),
                spec=it.get("spec"), source=it.get("source"),
                confidence=it.get("confidence", 0.5),
                assumptions="consolidation unavailable — raw per-sheet item, may duplicate",
            )
        )
    boms = [ExtractedBom(category=k, items=v) for k, v in by_cat.items()]
    return VisionExtraction(plan_type=spec.key, sheet_summary="raw per-sheet union", boms=boms)


def _mock_extraction(spec: registry.PlanTypeSpec) -> VisionExtraction:
    """Build a plausible extraction from each category's example items (offline mode)."""
    boms = [
        ExtractedBom(
            category=cat.key,
            items=[
                ExtractedItem(name=ex, confidence=0.4, assumptions="mock — example item, not read from a plan")
                for ex in cat.examples
            ],
        )
        for cat in spec.categories
        if cat.examples
    ]
    return VisionExtraction(plan_type=spec.key, sheet_summary="mock", boms=boms)
