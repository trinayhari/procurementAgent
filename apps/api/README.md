# Proq Backend

FastAPI REST/JSON API for the Proq procurement OS. **All data is persisted**
via SQLAlchemy (schema owned by Alembic) — projects, documents, suppliers, quotes,
RFQs, plus the dashboard/comparison/timeline/RFQ-inbox reference data. On first run
each table is seeded from the literals in `app/repositories/seed.py`; after that the
API reads exclusively from the database. The API returns **pure domain data** — all
styling (badges, chips, bars) stays in the frontend.

The default database is a zero-config local **SQLite** file. A production-grade
**PostgreSQL** service is part of the stack via `docker-compose.yml`:

```bash
cd apps/api
docker compose up -d                 # start Postgres
# then in apps/api/.env:
# PROCUREAI_DATABASE_URL=postgresql+psycopg2://procureai:procureai@localhost:5432/procureai
alembic upgrade head                 # create the schema in Postgres
```

Leaving `PROCUREAI_DATABASE_URL` unset falls back to `sqlite:///./procureai.db`, so
the app still runs without Docker.

## Stack

- **FastAPI** + **Pydantic v2** + **Uvicorn**
- **SQLAlchemy 2.0** + **Alembic** (SQLite by default)
- Python **3.8+**

## Setup

```bash
cd apps/api
python3.8 -m venv .venv          # or any Python >=3.8
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The server creates the SQLite file and seeds the 5 starter projects on first
startup, so it works out of the box. Alembic owns the schema for real migrations:

```bash
alembic upgrade head      # apply migrations (creates the projects table)
alembic revision --autogenerate -m "describe change"   # after editing models
```

The database URL defaults to `sqlite:///./procureai.db`; override with
`PROCUREAI_DATABASE_URL` (e.g. a Postgres DSN). Migrations and the app both read it.

> Note: startup uses `create_all` for zero-config dev. If you start the app first
> and later want to use Alembic on that same database, run `alembic stamp head`
> once so Alembic knows the schema is already at the latest revision.

- API root: `http://localhost:8000`
- Interactive docs (Swagger): `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

## Layout

```
app/
  main.py            FastAPI app, CORS, router mounting, startup init_db()
  config.py          settings (env vars via PROCUREAI_ prefix / .env)
  db.py              SQLAlchemy engine, session, get_db dependency, init_db()
  models/            SQLAlchemy ORM models (project.py)
  api/routes/        thin HTTP route modules (one per resource)
  schemas/           Pydantic request/response models
  repositories/      data access — projects.py (DB) + seed.py (in-memory rest)
  services/          business logic (reserved for phase 2)
migrations/          Alembic environment + versioned schema migrations
scripts/             dev scripts — export_openapi.py dumps openapi.json for the
                     frontend's `npm run gen:api` type generation
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
  extraction. See `apps/api/.env.example` for all tunables (model, DPI, page cap).
- **Human-in-the-loop.** AI extraction is a first draft. An estimator reviews the
  BOM in the Documents tab, edits items/quantities (`PUT …/line-items`, which
  recomputes counts and flags the doc `edited`), and approves it (`POST …/confirm`,
  setting `reviewed`). This is the intended path to procurement-grade quantities —
  AI takeoff + human verification — since visual takeoffs are inherently noisy.

## Persistence

Every domain entity has a SQLAlchemy model (`app/models/`) and a repository
(`app/repositories/`):

| Area | Model(s) | Repository |
| --- | --- | --- |
| Projects | `project.py` | `projects.py` |
| Documents + extracted BOMs | `document.py` | `documents.py` |
| Supplier directory + comms | `supplier.py` | `suppliers.py` |
| Quotes (ingested) | `quote.py` | `quotes.py` |
| Generated RFQs | `rfq.py` | `rfqs.py` |
| Found suppliers (search) | `found_supplier.py` | `sourcing.py` |
| Dashboard, overview cards, packages, line-item groups, comparisons, timeline, RFQ folders, demo RFQ inbox, demo quotes | `reference.py` | `reference.py` |

`app/repositories/seed.py` is now **only the seeding source**: its literals are
loaded into the DB once on first run (each repo has a `seed_*` function called from
`db.init_db()`). Routes read exclusively from the database, so all data survives a
restart.
