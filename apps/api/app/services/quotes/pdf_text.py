"""Extract the text layer of a PDF held in memory, in a child process.

PyMuPDF is a C extension; a malformed supplier attachment can fault natively
and take the whole API process down (the extraction pipeline hit exactly this
in prod — see services/extraction/isolated.py). Quote ingest runs the parse
here, in a throwaway interpreter: the bytes go in on stdin, text comes out on
stdout, and a crash or hang only ever kills the child.

Usage (parent): pdf_text.extract(data) → str ("" on any failure).
Usage (child):  python -m app.services.quotes.pdf_text < file.pdf
"""
import subprocess
import sys

_TIMEOUT_S = 60.0
# Enough for a long multi-page quote; keeps a pathological PDF from flooding memory.
_MAX_CHARS = 200_000


def _extract_inprocess(data: bytes) -> str:
    import fitz  # PyMuPDF

    with fitz.open(stream=data, filetype="pdf") as doc:
        return " ".join(page.get_text() for page in doc)


def extract(data: bytes, timeout: float = _TIMEOUT_S) -> str:
    """Text of a PDF (best effort). Never raises; returns "" when it can't."""
    if not data:
        return ""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.services.quotes.pdf_text"],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace")[:_MAX_CHARS].strip()


def main() -> int:
    data = sys.stdin.buffer.read()
    try:
        text = _extract_inprocess(data)
    except Exception:
        return 1
    sys.stdout.write(text[:_MAX_CHARS])
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
