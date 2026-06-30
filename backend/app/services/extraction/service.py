"""Extraction orchestrator.

`extract_document(path, plan_type)` is the one entry point the API uses. It is
TEXT-FIRST:
  • Vector CAD PDFs carry an embedded text layer with every callout, quantity, and
    schedule as exact text. When present, we send that text to a regular (non-vision)
    model in ONE call — fast, cheap, and more accurate than reading pixels.
  • Scanned PDFs / image uploads have no text layer, so they fall back to the vision
    pipeline: each sheet is rasterised to high-DPI tiles, read per-sheet in parallel,
    then a consolidation pass merges the per-sheet items into one deduplicated BOM.

Either way the category-keyed result is mapped onto the frontend's BOM groups
(`group`, `count`, `tone`, `items[{n, q}]`) via `_to_groups` — the only place
presentation is derived. A clearly-flagged mock runs when no key/SDK is present.
"""
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from app.config import settings
from app.services.extraction import registry, vision
from app.services.extraction.models import ExtractedBom, ExtractedItem, VisionExtraction
from app.services.extraction.pdf import (
    UnsupportedDocument,
    extract_text_pages,
    has_text_layer,
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


def _extract_sheets(spec: registry.PlanTypeSpec, path: str, n: int) -> Tuple[List[dict], int, int]:
    """Run the per-sheet extraction pass over the WHOLE document, in parallel.

    Each sheet is rendered as high-DPI tiles (so small fitting callouts are legible)
    and sent as one call. Returns (flat per-sheet items with provenance, sheets_ok,
    sheets_failed). A sheet that errors is skipped rather than failing the document.
    """
    def one(idx):
        label = f"Sheet {idx + 1} of {n}"
        tiles = to_page_tiles(
            path, idx,
            dpi=settings.vision_tile_dpi,
            cols=settings.vision_tile_cols,
            rows=settings.vision_tile_rows,
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
        return out

    items: List[dict] = []
    ok = failed = 0
    workers = max(1, min(settings.vision_max_workers, n))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(_safe(one), range(n)):
            if result is None:
                failed += 1
            else:
                ok += 1
                items.extend(result)
    return items, ok, failed


def _safe(fn):
    """Wrap a sheet worker so one bad sheet returns None instead of raising."""
    def wrapped(arg):
        try:
            return fn(arg)
        except Exception:
            return None
    return wrapped


def _vision_topup(spec, path, sheets, final) -> None:
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
            int(s["sheet"].split()[1]) - 1  # "Sheet N of M" -> N-1
            for s in sheets
            if any(kw.upper() in s["text"].upper() for kw in cat.sheet_keywords)
        ][:3]  # bound cost
        items, seen = [], set()
        for idx in targets:
            try:
                tiles = to_page_tiles(
                    path, idx,
                    dpi=settings.vision_tile_dpi,
                    cols=settings.vision_tile_cols,
                    rows=settings.vision_tile_rows,
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

    # Text-first — vector CAD PDFs carry the BOM as exact text; one cheap text call.
    # Skipped for plan types whose text layer is scrambled (prefer_vision): there the
    # schedules/plans are only legible as rendered images, so we fall through to the
    # per-sheet vision path below.
    if has_text_layer(path) and not spec.prefer_vision:
        sheets = extract_text_pages(path, settings.vision_max_pages)
        try:
            final = vision.extract_text(spec, sheets)
        except vision.VisionUnavailable as exc:
            return ExtractionResult([], 0, error=str(exc))
        # Targeted vision top-up for graphical disciplines (e.g. erosion control) that
        # carry no quantities in the text layer.
        _vision_topup(spec, path, sheets, final)
        groups, total = _to_groups(spec, final)
        summary = (final.sheet_summary or "").strip() or f"{len(sheets)} sheet(s) · text layer"
        return ExtractionResult(groups, total, summary=summary)

    # Fallback (scanned PDF / image): vision.
    # Pass 1 — per-sheet extraction over the whole document (each sheet tiled).
    try:
        per_sheet, ok, failed = _extract_sheets(spec, path, n_pages)
    except vision.VisionUnavailable as exc:
        return ExtractionResult([], 0, error=str(exc))
    if ok == 0:
        return ExtractionResult([], 0, error="Every sheet failed to extract")

    # Pass 2 — consolidate into one deduplicated BOM.
    if per_sheet:
        try:
            final = vision.consolidate(spec, per_sheet)
        except vision.VisionUnavailable:
            final = _fallback_consolidation(spec, per_sheet)  # union, no merge
    else:
        final = VisionExtraction(plan_type=spec.key, boms=[])

    groups, total = _to_groups(spec, final)
    summary = (final.sheet_summary or "").strip() or None
    note = f"{ok} sheet(s) read" + (f", {failed} failed" if failed else "")
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
