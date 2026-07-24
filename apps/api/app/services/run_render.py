"""Child-process entrypoint for isolated preview rendering.

Invoked as one of:

    python -m app.services.run_render count <file> <out.json>
    python -m app.services.run_render page  <file> <page-index> <width> <out.png>

Same rationale as extraction/run_extract.py: PyMuPDF can fault natively on a
malformed PDF, which would kill the whole API process. Previews are served on a
*read* path that any user can trigger repeatedly, so that blast radius matters
even more here — the parse runs in its own interpreter and a crash surfaces to
the parent as a non-zero exit code.
"""
import json
import sys

from app.services.extraction import pdf


def _count(path: str, out_path: str) -> None:
    try:
        out = {"ok": True, "pages": pdf.page_count(path)}
    except BaseException as exc:  # noqa: BLE001 — record any failure for the parent
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    with open(out_path, "w") as fh:
        json.dump(out, fh)


def _page(path: str, page_index: int, width: int, out_path: str) -> None:
    # Failures exit non-zero with the reason on stderr; the parent turns that
    # into a normal exception. PageOutOfRange gets its own code so the caller
    # can answer 404 rather than 500.
    try:
        data = pdf.render_page_png(path, page_index, width=width)
    except pdf.PageOutOfRange as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3)
    with open(out_path, "wb") as fh:
        fh.write(data)


def main() -> None:
    mode = sys.argv[1]
    if mode == "count":
        _count(sys.argv[2], sys.argv[3])
    elif mode == "page":
        _page(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5])
    else:
        print(f"unknown mode '{mode}'", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
