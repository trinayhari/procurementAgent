"""Child-process entrypoint for isolated timeline extraction.

Invoked as `python -m app.services.extraction.run_timeline <file> <out.json>`.
Same rationale as run_extract: PyMuPDF can fault natively on a malformed PDF, so
the parse runs in its own interpreter and the API process is never affected.
"""
import json
import sys

from app.services.extraction import timeline


def main() -> None:
    path, out_path = sys.argv[1], sys.argv[2]
    try:
        r = timeline.extract_timeline(path)
        out = {"ok": True, "events": r.events, "error": r.error, "summary": r.summary}
    except BaseException as exc:  # noqa: BLE001 — record any failure for the parent
        out = {"ok": False, "error_fatal": f"{type(exc).__name__}: {exc}"}
    with open(out_path, "w") as fh:
        json.dump(out, fh)


if __name__ == "__main__":
    main()
