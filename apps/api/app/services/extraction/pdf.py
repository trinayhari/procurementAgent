"""Render uploaded documents to images for the vision model.

GPT-4.1 vision consumes images, so PDFs are rasterised page-by-page with PyMuPDF
(`fitz`). Image uploads (PNG/JPG) are passed through. DWG/ZIP are out of scope for
the vision path and raise `UnsupportedDocument` so the caller can flag the doc.

Output is a list of base64-encoded PNG strings (no data-URL prefix); `vision.py`
wraps them as data URLs.
"""
import base64
import gc
import os
from typing import List

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PDF_EXTS = {".pdf"}


class UnsupportedDocument(Exception):
    """Raised for file types the vision pipeline cannot rasterise (DWG, ZIP, …)."""


class PageOutOfRange(Exception):
    """Raised when a requested page index doesn't exist in the document."""


def page_count(path: str) -> int:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return 1
    if ext in PDF_EXTS:
        import fitz  # PyMuPDF; imported lazily so the API boots without it

        try:
            with fitz.open(path) as doc:
                return doc.page_count
        except Exception as exc:  # corrupt/truncated PDF — treat as unsupported
            raise UnsupportedDocument(f"Cannot open PDF: {exc}") from exc
    raise UnsupportedDocument(f"Cannot count pages for '{ext}'")


def to_base64_images(path: str, *, dpi: int = 150, max_pages: int = 12) -> List[str]:
    """Return up to `max_pages` base64 PNG pages rendered from the document.

    `dpi` trades detail against token cost — 150 is a good balance for plan sheets;
    bump it for dense schedules. `max_pages` caps cost on large plan sets.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in IMAGE_EXTS:
        with open(path, "rb") as fh:
            return [base64.b64encode(fh.read()).decode("ascii")]

    if ext in PDF_EXTS:
        import fitz  # PyMuPDF

        images: List[str] = []
        with fitz.open(path) as doc:
            for page in doc:
                if len(images) >= max_pages:
                    break
                pix = page.get_pixmap(dpi=dpi)
                images.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
                pix = None  # release the raw pixmap immediately — it dwarfs the PNG
        gc.collect()
        return images

    raise UnsupportedDocument(f"Unsupported document type '{ext}' for vision extraction")


def render_page_png(path: str, page_index: int, *, width: int = 1400) -> bytes:
    """Render one PDF page to PNG bytes, scaled so the page is ~`width` px wide.

    Feeds the in-app document preview (see services/preview.py). Scaling to a
    target width rather than a fixed DPI keeps a 36x24 plan sheet and a
    letter-size schedule at comparable byte sizes — a fixed DPI would make the
    plan sheet many times heavier for no extra legibility on screen.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in PDF_EXTS:
        raise UnsupportedDocument(f"Cannot render '{ext}' pages")

    import fitz  # PyMuPDF

    with fitz.open(path) as doc:
        if page_index < 0 or page_index >= doc.page_count:
            raise PageOutOfRange(f"page {page_index} of a {doc.page_count}-page document")
        page = doc[page_index]
        # Clamp the zoom so a pathological page box can't produce a huge pixmap.
        zoom = max(0.1, min(4.0, width / max(1.0, page.rect.width)))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        data = pix.tobytes("png")
        pix = None  # release the raw pixmap immediately — it dwarfs the PNG
    gc.collect()
    return data


def has_text_layer(path: str, min_chars: int = 500) -> bool:
    """True if the PDF carries an embedded text layer (vector CAD export) rather
    than being a scan. Text-layer PDFs are extracted with a fast/cheap text model;
    scans fall back to vision."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in PDF_EXTS:
        return False
    import fitz  # PyMuPDF

    total = 0
    with fitz.open(path) as doc:
        for page in doc:
            total += len(page.get_text().strip())
            if total >= min_chars:
                return True
    return False


def extract_text_pages(path: str, max_pages: int = 30) -> List[dict]:
    """Return [{'sheet': 'Sheet N of M', 'index': N-1, 'text': ...}] per text-bearing page.

    Whitespace is collapsed to keep the prompt compact; CAD text has no meaningful
    line structure anyway. Empty pages are skipped.

    CAD/plot exports frequently stack identical copies of the drawing's text on top
    of itself (a screen layer + a plot layer, etc.), so the same callout appears 2-3x
    at the exact same coordinates. Left in, that inflates every quantity the model
    sums. We drop words that repeat at the same position (rounded to whole points),
    which removes the stacked copies but keeps genuinely repeated callouts (they sit
    at different coordinates).
    """
    import fitz  # PyMuPDF

    pages: List[dict] = []
    with fitz.open(path) as doc:
        total = min(doc.page_count, max_pages)
        for i in range(total):
            text = _dedup_page_text(doc[i])
            if text:
                pages.append({"sheet": f"Sheet {i + 1} of {total}", "index": i, "text": text})
    return pages


def _dedup_page_text(page) -> str:
    """Embedded page text with position-stacked duplicate words removed.

    Words are returned as (x0, y0, x1, y1, text, block, line, word_no). We keep the
    first occurrence of each (text, round(x0), round(y0)) and re-emit in reading
    order (top-to-bottom, left-to-right). For ordinary single-layer PDFs nothing is
    stacked, so this is a no-op beyond the whitespace collapse.
    """
    words = page.get_text("words")
    if not words:
        return ""
    seen, kept = set(), []
    for w in words:
        x0, y0, _x1, _y1, text = w[0], w[1], w[2], w[3], w[4]
        key = (text, round(x0), round(y0))
        if key in seen:
            continue
        seen.add(key)
        kept.append((round(y0 / 3), x0, text))  # ~3pt rows to group a line together
    kept.sort(key=lambda k: (k[0], k[1]))
    return " ".join(t for _, _, t in kept)


def to_page_tiles(
    path: str,
    page_index: int,
    *,
    dpi: int = 200,
    cols: int = 3,
    rows: int = 2,
    overlap: float = 0.08,
) -> List[str]:
    """Render one PDF page as a grid of overlapping high-DPI tiles (base64 PNG).

    Large plan sheets (24x36) lose small callout text when downscaled to a single
    image. Tiling renders each region at native DPI so the model can read fitting
    callouts, schedules, and bend angles. `overlap` (fraction of tile size) keeps
    items spanning a tile boundary intact; the prompt tells the model these tiles
    are one sheet so it does not double-count the overlap.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in PDF_EXTS:
        # Non-PDF (single image) → just return the whole image.
        return to_base64_images(path, dpi=dpi, max_pages=1)

    import fitz  # PyMuPDF

    tiles: List[str] = []
    with fitz.open(path) as doc:
        page = doc[page_index]
        r = page.rect
        tw, th = r.width / cols, r.height / rows
        ox, oy = tw * overlap, th * overlap
        for row in range(rows):
            for col in range(cols):
                x0 = max(r.x0, r.x0 + col * tw - ox)
                y0 = max(r.y0, r.y0 + row * th - oy)
                x1 = min(r.x1, r.x0 + (col + 1) * tw + ox)
                y1 = min(r.y1, r.y0 + (row + 1) * th + oy)
                clip = fitz.Rect(x0, y0, x1, y1)
                pix = page.get_pixmap(dpi=dpi, clip=clip)
                tiles.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
                pix = None  # release the raw pixmap immediately — it dwarfs the PNG
    gc.collect()  # reclaim the page's pixmaps before the next sheet is rendered
    return tiles
