"""Render uploaded documents to images for the vision model.

GPT-4.1 vision consumes images, so PDFs are rasterised page-by-page with PyMuPDF
(`fitz`). Image uploads (PNG/JPG) are passed through. DWG/ZIP are out of scope for
the vision path and raise `UnsupportedDocument` so the caller can flag the doc.

Output is a list of base64-encoded PNG strings (no data-URL prefix); `vision.py`
wraps them as data URLs.
"""
import base64
import os
from typing import List

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PDF_EXTS = {".pdf"}


class UnsupportedDocument(Exception):
    """Raised for file types the vision pipeline cannot rasterise (DWG, ZIP, …)."""


def page_count(path: str) -> int:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return 1
    if ext in PDF_EXTS:
        import fitz  # PyMuPDF; imported lazily so the API boots without it

        with fitz.open(path) as doc:
            return doc.page_count
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
        return images

    raise UnsupportedDocument(f"Unsupported document type '{ext}' for vision extraction")


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
    return tiles
