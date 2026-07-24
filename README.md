# Proq

AI-native procurement OS for construction — frontend implemented from the
[Claude Design project](https://claude.ai/design/p/89235166-b09a-445b-b668-bd65e6698d9c)
`ProcureAI.dc.html` (the prototype predates the rebrand).

## Stack

- **Frontend:** React 18 + Vite + **TypeScript**. Styling is plain CSS variables
  (light/dark + accent themes) plus inline styles, ported verbatim from the design
  prototype. The API client is **type-safe end-to-end**: TS types are generated
  from the backend's OpenAPI schema (see [Type generation](#type-generation)).
- **Backend:** FastAPI + Pydantic v2 (Python 3.8+) serving a REST/JSON API. See
  [`apps/api/README.md`](apps/api/README.md).

The repo is an **npm-workspaces monorepo**: `apps/web` is the frontend, `apps/api`
is the backend, and any new app goes under `apps/`. `npm install` is run once from
the repo root and installs every workspace.

## Run

**Frontend**

```bash
npm install        # once, from the repo root — covers all workspaces
npm run dev        # http://localhost:5173
npm run build      # build every workspace (web: tsc --noEmit then vite build)
npm run typecheck  # type-check every workspace
npm run gen:api    # regenerate apps/web/src/api-types.ts from the backend OpenAPI schema
```

The root scripts delegate to the web workspace; run them directly with
`npm run dev --workspace @proq/web` if you prefer.

**Backend** (required — every screen is API-driven and auth-gated)

```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
uvicorn app.main:app --reload --port 8000   # docs at /docs
python -m pytest tests -q                   # backend test suite (mock providers)
```

Every API route requires a login (JWT). Register the first account from the
login screen, or set `PROCUREAI_SEED_DEMO_DATA=true` for the demo account +
sample data. External providers (OpenAI, Google Maps, Gmail) are optional —
without keys the app runs on clearly-flagged mocks, end to end. The test
suite force-blanks all provider credentials so it can never send real email.

To send real RFQ emails (including from a custom From address per user), follow
the step-by-step guide in [docs/email-setup.md](docs/email-setup.md).

The frontend reads `VITE_API_URL` (default `http://localhost:8000`); copy
`apps/web/.env.example` to `apps/web/.env` to override. On load,
`apps/web/src/api.ts` hydrates the model from the API; if a request fails the
affected section renders its empty state (there is no fake fallback data).

## Type generation

The frontend types its API client against the backend's contract instead of
hand-maintaining duplicate types. `npm run gen:api` dumps the FastAPI OpenAPI
schema to `apps/api/openapi.json` (via `apps/api/scripts/export_openapi.py`) and
runs [`openapi-typescript`](https://github.com/openapi-ts/openapi-typescript) to
write `apps/web/src/api-types.ts`. `apps/web/src/api.ts` re-exports friendly
aliases (`Document`, `Project`, `Quote`, …) from that file, so any change to a
Pydantic model surfaces as a TypeScript error after regenerating.

The script uses the backend virtualenv at `apps/api/.venv` by default; override
with the `PYTHON` env var (e.g. `PYTHON=python npm run gen:api` on Windows, after
activating the venv). Re-run it whenever the backend schemas change, then commit
the regenerated `apps/web/src/api-types.ts`.

## Structure

Workspaces live under `apps/`; the repo root holds only shared config
(`package.json`, `vercel.json`, `render.yaml`, `.github/`) and the docs.

| File | Purpose |
| --- | --- |
| `apps/web/src/index.css` | Design tokens (`:root`, `[data-theme=dark]`, accents) and base styles. |
| `apps/web/src/lib.tsx` | `css()` string→style helper, `Box` (hover-aware element), icon map, badge/chip/bar/logo style helpers. |
| `apps/web/src/model.ts` | `buildModel(state, set, props)` — mirrors the prototype's `renderVals()`, producing all computed data and styles each render. Prefers `props.data` (from the API), falling back to baked-in literals. Exports the `State`, `ModelProps`, and `Model` types. |
| `apps/web/src/api.ts` | Backend client — `loadModelData()` fetches and reshapes the API payload into the keys `buildModel` consumes. Typed against `apps/web/src/api-types.ts`. |
| `apps/web/src/api-types.ts` | **Generated** from the backend OpenAPI schema (`npm run gen:api`). Do not edit by hand. |
| `apps/api/` | FastAPI REST API (see its own README). Serves the same data as pure JSON. |
| `apps/web/src/App.tsx` | All screens: dashboard, projects, suppliers, settings, and the project workspace tabs (overview, documents, suppliers, RFQs, quotes, quote comparison, timeline), plus the supplier drawer and mobile nav. |

## Screens

- **Dashboard** — portfolio metrics, project overview table, recent activity.
- **Projects / Suppliers / Settings** — top-level sections.
- **Project workspace** (open any project) — tabbed:
  Overview · Documents (with AI-extracted materials) · Suppliers · RFQs
  (email thread view) · Quotes table · **Quote Comparison** (flagship,
  with AI recommendation) · Timeline (gantt + milestones).

State (active tab, selected document/RFQ, theme, supplier drawer, mobile nav)
lives in `App`'s `useState` and flows through `buildModel`.
