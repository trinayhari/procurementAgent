# ProcureAI Backend

FastAPI REST/JSON API for the ProcureAI procurement OS. Phase 1 serves the same
data the React prototype previously hardcoded in `src/model.js`, from an in-memory
seed (`app/repositories/seed.py`). The API returns **pure domain data** — all
styling (badges, chips, bars) stays in the frontend.

## Stack

- **FastAPI** + **Pydantic v2** + **Uvicorn**
- Python **3.8+**

## Setup

```bash
cd backend
python3.8 -m venv .venv          # or any Python >=3.8
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- API root: `http://localhost:8000`
- Interactive docs (Swagger): `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

## Layout

```
app/
  main.py            FastAPI app, CORS, router mounting
  config.py          settings (env vars via PROCUREAI_ prefix / .env)
  api/routes/        thin HTTP route modules (one per resource)
  schemas/           Pydantic request/response models
  repositories/      data access — seed.py is the phase-1 in-memory store
  services/          business logic (reserved for phase 2)
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/dashboard` | Portfolio metrics + activity feed |
| GET | `/api/projects` | Project list |
| GET | `/api/projects/{id}` | Project detail (overview cards + packages) |
| GET | `/api/projects/{id}/documents` | Project documents |
| GET | `/api/projects/{id}/line-items` | AI-extracted material groups |
| GET | `/api/projects/{id}/suppliers` | Suppliers on a project |
| GET | `/api/projects/{id}/quotes` | Quotes table |
| GET | `/api/projects/{id}/rfqs` | RFQ list |
| GET | `/api/projects/{id}/rfq-folders` | RFQ folder counts |
| GET | `/api/projects/{id}/timeline` | Milestones + gantt |
| GET | `/api/projects/{id}/packages/{pkg}/comparison` | Quote comparison + AI recommendation |
| GET | `/api/suppliers` / `/api/suppliers/{id}` | Suppliers + comms history |
| GET | `/api/rfqs/{id}` | RFQ detail + message thread |
| GET | `/api/documents/plan-types` | Plan types the extractor supports (upload selector) |
| GET | `/api/documents/{id}` | Document detail |
| GET | `/api/documents/{id}/line-items` | BOM groups extracted from one document |
| PUT | `/api/documents/{id}/line-items` | Human-in-the-loop: save a reviewer's edited BOM |
| POST | `/api/documents/{id}/confirm` | Human-in-the-loop: approve a document's BOM |

### Command (action) endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/documents` | Upload a plan set (multipart `file` + `plan_type`); runs GPT-4.1 vision extraction in the background |
| POST | `/api/documents/{id}/analyze` | Re-run extraction for an uploaded document |
| POST | `/api/rfqs/{id}/messages` | Send a reply in the thread |
| POST | `/api/rfqs/{id}/followup` | Draft an AI follow-up (stub) |
| POST | `/api/quotes/{id}/select` | Select supplier & issue PO |

## Document extraction (GPT-4.1 vision)

`app/services/extraction/` turns uploaded plan sets into Bills of Materials.

- **Modular by plan type.** Each plan type is a `PlanTypeSpec` (key, label, BOM
  categories with descriptions/examples/tones) in `plan_types.py`, registered via
  `registry.py`. Adding building/electrical/etc. plans later is just registering a
  new spec — the prompt builder, vision call, and orchestrator are all generic over
  the registry. Specs can ship `enabled=False` ("coming soon" in the UI) while being
  tuned. `site_plan` (water · sewer · storm drain · erosion control) ships enabled.
- **Pipeline.** `pdf.py` rasterises PDFs/images to pages → `prompts.py` builds the
  takeoff prompt from the spec → `vision.py` calls GPT-4.1 with Structured Outputs
  (`response_format=VisionExtraction`) → `service.py` maps category-keyed results to
  the frontend's BOM groups.
- **Offline mode.** With no `PROCUREAI_OPENAI_API_KEY`, a clearly-flagged mock
  extraction runs so the upload UX works without API access. Set the key for live
  extraction. See `backend/.env.example` for all tunables (model, DPI, page cap).
- **Human-in-the-loop.** AI extraction is a first draft. An estimator reviews the
  BOM in the Documents tab, edits items/quantities (`PUT …/line-items`, which
  recomputes counts and flags the doc `edited`), and approves it (`POST …/confirm`,
  setting `reviewed`). This is the intended path to procurement-grade quantities —
  AI takeoff + human verification — since visual takeoffs are inherently noisy.

## Phase 2 (later)

Replace `app/repositories/seed.py` with SQLAlchemy models + a real database
(Alembic migrations). Routes and schemas stay unchanged. Persist uploaded documents
and their extracted BOMs alongside the rest of the domain data.
