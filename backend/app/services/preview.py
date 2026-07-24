"""Server-rendered page images for the in-app document preview.

The preview used to embed the original file in an ``<iframe>``, which only
works where the browser ships a PDF viewer plugin. Chrome has one; embedded
webviews generally don't — there the panel rendered blank or kicked off a
download instead. Rasterising pages server-side and serving plain ``<img>``
data renders identically everywhere, and it also gives non-PDF uploads
(PNG/JPG scans) a real preview.

Rendering goes through PyMuPDF in a child process (see
``extraction/isolated.py`` for the full rationale — a malformed PDF can fault
natively and take the API process with it). That subprocess costs ~0.5s, so
rendered pages are cached on disk keyed by (document content, page, width) and
the cost is paid once per page rather than once per view.
"""
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.services import storage
from app.services.extraction import pdf

logger = logging.getLogger("procureai.preview")

# Uploads we can turn into a page image. Anything else (CSV/XLSX) has no visual
# form and falls back to "open the original" in the UI.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class RenderFailed(Exception):
    """Rendering crashed, timed out, or the file could not be read."""


class PageOutOfRange(Exception):
    """The requested page doesn't exist in the document."""


@dataclass
class RenderedPage:
    data: bytes
    media_type: str


def is_renderable(locator: Optional[str]) -> bool:
    """True if we can produce a page image for this file."""
    if not locator:
        return False
    ext = os.path.splitext(locator)[1].lower()
    return ext in _IMAGE_EXTS or ext in pdf.PDF_EXTS


def page_count(locator: str, *, known: int = 0) -> int:
    """Pages available for preview: the count recorded at upload when we have
    one, otherwise probed from the file (isolated, same as rendering).

    Returns 0 when the count can't be determined, which the UI treats as
    "not previewable" and falls back to opening the original.
    """
    ext = os.path.splitext(locator)[1].lower()
    if ext in _IMAGE_EXTS:
        return 1
    if known > 0:
        return known
    if ext not in pdf.PDF_EXTS:
        return 0
    try:
        with storage.local_copy(locator) as path:
            return _probe_isolated(path)
    except Exception:  # noqa: BLE001 — a missing count only costs the preview
        logger.warning("Could not count pages for %s", locator, exc_info=True)
        return 0


def render_page(locator: str, page_index: int, *, cache_key: str, width: int = 0) -> RenderedPage:
    """Return one page of `locator` as an image, rendering it if not cached.

    `cache_key` identifies the file's *content* (the upload checksum), so a
    replaced document never serves the previous file's pages from cache.
    """
    width = width or settings.preview_width_px
    ext = os.path.splitext(locator)[1].lower()
    media_type = _MEDIA_TYPES.get(ext, "image/png") if ext in _IMAGE_EXTS else "image/png"

    cached = _cache_path(cache_key, page_index, width)
    data = _read_cached(cached)
    if data is not None:
        return RenderedPage(data, media_type)

    if ext in _IMAGE_EXTS:
        # An image upload is a single page — serve it as-is; the browser scales it.
        if page_index != 0:
            raise PageOutOfRange(f"page {page_index} of a 1-page document")
        with storage.local_copy(locator) as path:
            with open(path, "rb") as fh:
                data = fh.read()
    else:
        with storage.local_copy(locator) as path:
            data = _render_isolated(path, page_index, width)

    _write_cached(cached, data)
    return RenderedPage(data, media_type)


# ------------------------------------------------------------------ internals
def _cache_dir() -> str:
    path = settings.preview_cache_dir or os.path.join(tempfile.gettempdir(), "proq-previews")
    os.makedirs(path, exist_ok=True)
    return path


def _cache_path(cache_key: str, page_index: int, width: int) -> str:
    # Hash the key: it may be a storage locator (slashes) or a checksum.
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:20]
    return os.path.join(_cache_dir(), f"{digest}-p{page_index}-w{width}.img")


def _read_cached(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _write_cached(path: str, data: bytes) -> None:
    """Write via a temp file + rename so a concurrent reader never sees a
    half-written image (two requests for the same page can race)."""
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".preview-")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:  # a cache we can't write is a slowdown, not a failure
        logger.warning("Could not cache preview page at %s", path, exc_info=True)


def _probe_isolated(path: str, timeout: float = 60.0) -> int:
    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="preview_count_")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.services.run_render", "count", path, out_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if proc.returncode != 0:
            return 0
        with open(out_path) as fh:
            data = json.load(fh)
        return int(data.get("pages") or 0) if data.get("ok") else 0
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def _render_isolated(path: str, page_index: int, width: int, timeout: float = 120.0) -> bytes:
    fd, out_path = tempfile.mkstemp(suffix=".png", prefix="preview_page_")
    os.close(fd)
    try:
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "app.services.run_render", "page",
                    path, str(page_index), str(width), out_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RenderFailed(f"rendering page {page_index} timed out after {timeout:.0f}s")
        if proc.returncode == 3:
            raise PageOutOfRange(f"page {page_index} does not exist in this document")
        if proc.returncode != 0:
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
            raise RenderFailed(
                f"render subprocess exited {proc.returncode} "
                f"(likely a native crash while parsing the PDF). stderr: {tail or '<none>'}"
            )
        with open(out_path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass
