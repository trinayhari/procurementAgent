"""Dump the FastAPI OpenAPI schema to apps/api/openapi.json.

The frontend's type-generation step (`npm run gen:api`) reads this file with
openapi-typescript to produce `src/api-types.ts`, keeping the TS client in sync
with the Python/Pydantic models. Run from the backend dir with the venv active:

    python scripts/export_openapi.py

The spec is a build artifact, not a served surface, so it is exported with
every router mounted: the bench routes are off at runtime by default (they are
unauthenticated, see config.bench_enabled) but @proq/bench still needs their
types. Forcing the flag here also makes the output independent of whoever's
environment runs the export, which is what the CI drift check compares.
"""

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Before app.main is imported: the bench router is mounted at import time.
os.environ["PROCUREAI_BENCH_ENABLED"] = "true"
os.environ["PROCUREAI_ENV"] = "development"

from app.main import app  # noqa: E402  (import after sys.path tweak)

OUT = BACKEND_ROOT / "openapi.json"


def main() -> None:
    spec = app.openapi()
    OUT.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"Wrote {OUT} ({len(spec.get('components', {}).get('schemas', {}))} schemas)")


if __name__ == "__main__":
    main()
