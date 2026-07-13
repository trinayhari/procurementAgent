"""Run extraction in an isolated child process.

PDF parsing/rasterisation goes through PyMuPDF (a C extension). A malformed or
unusually large plan set can trigger a *native* fault (segfault/abort) deep in
MuPDF — which kills the whole interpreter with no Python traceback. In the API
process that means the server crashes and every in-flight request dies (and the
extraction's document is left stranded).

Running `extract_document` in a separate `subprocess` contains that blast
radius: if the child faults, only the child dies; the parent sees a non-zero
exit code and raises a normal Python exception, so the caller marks the document
'Failed' and the API keeps serving. A hang is bounded by `timeout`.

A plain subprocess (rather than multiprocessing) is used deliberately: spawn/fork
under a running uvicorn server is fragile (re-imports __main__ / can deadlock on
locks held by server threads). A fresh `python -m` interpreter has neither issue.
"""
import json
import os
import subprocess
import sys
import tempfile

from app.services.extraction.service import ExtractionResult
from app.services.extraction.timeline import TimelineResult


def run(path: str, plan_type: str, timeout: float = 900.0) -> ExtractionResult:
    """Extract in a child process and return the `ExtractionResult`.

    Raises RuntimeError if the child crashed (native fault) or reported an error,
    or subprocess.TimeoutExpired if it ran past `timeout`. Both are ordinary
    exceptions the caller already handles by marking the document 'Failed'.
    """
    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="extract_")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.services.extraction.run_extract", path, plan_type, out_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-500:]
            raise RuntimeError(
                f"extraction subprocess exited {proc.returncode} "
                f"(likely a native crash while parsing the PDF). stderr: {tail or '<none>'}"
            )
        with open(out_path) as fh:
            data = json.load(fh)
        if not data.get("ok"):
            raise RuntimeError(data.get("error_fatal", "unknown extraction error"))
        return ExtractionResult(
            data["groups"],
            data["total_items"],
            mocked=data["mocked"],
            error=data["error"],
            summary=data["summary"],
        )
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def run_timeline(path: str, timeout: float = 600.0) -> TimelineResult:
    """Extract a document's timeline in a child process (same isolation rationale
    as `run` — the PDF parse can fault natively)."""
    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="timeline_")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.services.extraction.run_timeline", path, out_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-500:]
            raise RuntimeError(
                f"timeline subprocess exited {proc.returncode} "
                f"(likely a native crash while parsing the PDF). stderr: {tail or '<none>'}"
            )
        with open(out_path) as fh:
            data = json.load(fh)
        if not data.get("ok"):
            raise RuntimeError(data.get("error_fatal", "unknown timeline extraction error"))
        return TimelineResult(data["events"], error=data["error"], summary=data["summary"])
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass
