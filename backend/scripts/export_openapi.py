"""Dump the FastAPI OpenAPI schema to backend/openapi.json.

The frontend's type-generation step (`npm run gen:api`) reads this file with
openapi-typescript to produce `src/api-types.ts`, keeping the TS client in sync
with the Python/Pydantic models. Run from the backend dir with the venv active:

    python scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402  (import after sys.path tweak)

OUT = BACKEND_ROOT / "openapi.json"


def main() -> None:
    spec = app.openapi()
    OUT.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"Wrote {OUT} ({len(spec.get('components', {}).get('schemas', {}))} schemas)")


if __name__ == "__main__":
    main()
