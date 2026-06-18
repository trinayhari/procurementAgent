# ProcureAI

AI-native procurement OS for construction — frontend implemented from the
[Claude Design project](https://claude.ai/design/p/89235166-b09a-445b-b668-bd65e6698d9c)
`ProcureAI.dc.html`.

## Stack

- **Frontend:** React 18 + Vite. Styling is plain CSS variables (light/dark +
  accent themes) plus inline styles, ported verbatim from the design prototype.
- **Backend:** FastAPI + Pydantic v2 (Python 3.8+) serving a REST/JSON API. See
  [`backend/README.md`](backend/README.md).

## Run

**Frontend**

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # production build to dist/
```

**Backend** (optional — the UI falls back to baked-in data when it's down)

```bash
cd backend
python3.8 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000   # docs at /docs
```

The frontend reads `VITE_API_URL` (default `http://localhost:8000`); copy
`.env.example` to `.env` to override. On load, `src/api.js` hydrates the model
from the API; if the request fails, `src/model.js` renders its literal data so
the app always works.

## Structure

| File | Purpose |
| --- | --- |
| `src/index.css` | Design tokens (`:root`, `[data-theme=dark]`, accents) and base styles. |
| `src/lib.jsx` | `css()` string→style helper, `Box` (hover-aware element), icon map, badge/chip/bar/logo style helpers. |
| `src/model.js` | `buildModel(state, set, props)` — mirrors the prototype's `renderVals()`, producing all computed data and styles each render. Prefers `props.data` (from the API), falling back to baked-in literals. |
| `src/api.js` | Backend client — `loadModelData()` fetches and reshapes the API payload into the keys `buildModel` consumes. |
| `backend/` | FastAPI REST API (see its own README). Serves the same data as pure JSON. |
| `src/App.jsx` | All screens: dashboard, projects, suppliers, settings, design system, and the project workspace tabs (overview, documents, suppliers, RFQs, quotes, quote comparison, timeline), plus the supplier drawer and mobile nav. |

## Screens

- **Dashboard** — portfolio metrics, project overview table, recent activity.
- **Projects / Suppliers / Settings / Design System** — top-level sections.
- **Project workspace** (open any project) — tabbed:
  Overview · Documents (with AI-extracted materials) · Suppliers · RFQs
  (email thread view) · Quotes table · **Quote Comparison** (flagship,
  with AI recommendation) · Timeline (gantt + milestones).

State (active tab, selected document/RFQ, theme, supplier drawer, mobile nav)
lives in `App`'s `useState` and flows through `buildModel`.
