"""Child-process entrypoint for isolated extraction.

Invoked as `python -m app.services.extraction.run_extract <pdf> <plan_type> <out.json>`.
Runs the extraction and writes the result as JSON to <out.json>. Kept tiny and
free of server imports so the child starts fast. If the PDF parser faults
natively, this process dies with a non-zero exit code and the parent (see
`isolated.run`) reports it — the API process is never affected.
"""
import json
import sys

from app.services import extraction


def main() -> None:
    path, plan_type, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        r = extraction.extract_document(path, plan_type)
        out = {
            "ok": True,
            "groups": r.groups,
            "total_items": r.total_items,
            "mocked": r.mocked,
            "error": r.error,
            "summary": r.summary,
        }
    except BaseException as exc:  # noqa: BLE001 — record any failure for the parent
        out = {"ok": False, "error_fatal": f"{type(exc).__name__}: {exc}"}
    with open(out_path, "w") as fh:
        json.dump(out, fh)


if __name__ == "__main__":
    main()
