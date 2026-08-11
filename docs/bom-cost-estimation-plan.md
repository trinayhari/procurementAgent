# BOM Cost Benchmarking — Implementation Plan

Branch: `feat/bom-cost-estimation`. Status: **exploration + design only, nothing
implemented.**

## Goal

Show the buyer roughly what their materials *should* cost, so they can tell
whether a quote is fair. This is a **price sanity check, not an estimating
tool** — the output is a reference range with a sample size behind it, not a
number anyone would put in a bid.

Two moments matter:

1. **After quotes arrive** (primary) — "Ferguson quoted $41.00/LF for 12" DI
   Class 350; typical in the Raleigh–Durham area is $36–$40 across 14 quotes.
   This one is ~8% high."
2. **Before the RFQ goes out** (secondary) — a rough package-level range so the
   buyer knows what to expect.

The price source is **our own quote history** — every quote we ingest already
records a per-line unit price. The corpus is the asset; the feature gets better
the more the platform is used.

Benchmarks are **regional**. A national average is close to useless here:
delivered material prices vary widely by market, and a buyer in one metro
comparing against another's prices would draw the wrong conclusion. Region is a
first-class dimension of the corpus, not a later refinement — see §3.3.

---

## 1. What exists today

### 1.1 Projects

`apps/api/app/models/project.py` — one table, org-scoped, string ids
(`riverside`, or a slug for user-created ones). It is a **display-shaped**
record: `value` is a formatted string (`"$4.2M"`), not a number, and
`progress` / `risk` / `bar_color` are precomputed styling hints carried over
from the design prototype. `lat`/`lng` are cached geocodes of `loc` — the only
numeric geography available, and the hook for any future regional adjustment.

Sub-resources hang off `/api/projects/{id}/…` in
[projects.py](apps/api/app/api/routes/projects.py) and
[sourcing.py](apps/api/app/api/routes/sourcing.py).

### 1.2 BOM items

**There is no line-item table.** A BOM is a JSON blob on the document row:

- [`documents.line_items`](apps/api/app/models/document.py:54) — `Text`, JSON of
  `[{group, count, tone, items: [{n, q}]}]`.
- `n` = material name, `q` = **quantity as a display string** (`"2,400 LF"`,
  or `"—"` when unknown). See
  [`_quantity_display`](apps/api/app/services/extraction/service.py:56).
- Read/write through [`documents_repo`](apps/api/app/repositories/documents.py):
  `set_line_items` (extractor), `save_line_items` (human edit, sets
  `edited=True`), `get_line_items` (falls back to the global seed
  `line_item_groups` table for demo docs with no plan type).
- A hand-built **custom BOM** is just a document with
  `plan_type == "custom_bom"` ([documents.py:24](apps/api/app/repositories/documents.py:24)).

Aggregation from documents → a *buy-package* BOM happens in
[`_line_items_for_package`](apps/api/app/api/routes/sourcing.py:317): walks every
document on the project, keeps groups whose label maps to the package via
[`packages.category_for_label`](apps/api/app/services/sourcing/packages.py:318),
dedupes by lowercased name, and enforces the **approval gate** (`reviewed=True`
only). Same set of items an RFQ quotes — the right input for a pre-RFQ range.

### 1.3 The blocking gap

The extractor already produces everything needed:
[`ExtractedItem`](apps/api/app/services/extraction/models.py:13) carries
`quantity: float`, `unit`, `spec`, `feature`, `source`, `confidence`,
`assumptions`. But [`_to_groups`](apps/api/app/services/extraction/service.py:64)
collapses it to `{"n": name, "q": display_string}` and **discards the rest**.

You cannot compare `$/LF` without a unit. Restoring this is milestone 1 (§4.1).

### 1.4 Existing API patterns (to follow, not reinvent)

- **Routers**: `APIRouter(prefix="/api/…", tags=[…])` in
  `apps/api/app/api/routes/`, registered in
  [main.py:105](apps/api/app/main.py:105) with a global auth dependency.
- **Tenancy**: every handler reads `current_user.organization_id`, calls
  `_require_project(org_id, project_id, db)` which 404s (never 403s) for another
  tenant's id, and passes `org_id` into every repo call. Tenant tables carry
  `organization_id` and appear in [`SCOPED_TABLES`](apps/api/app/db.py:36).
  **§3.4 deliberately breaks this pattern and needs care.**
- **Layering**: route → `app/repositories/*` (thin, `(db, org_id, …)`) →
  `app/models/*`. Logic in `app/services/*`.
- **Schemas**: Pydantic v2 in `app/schemas/*`, **camelCase** fields. `npm run
  gen:api` regenerates `apps/web/src/api-types.ts`; the web client only ever uses
  generated types.
- **Long work**: `BackgroundTasks` + a durable `background_jobs` row
  (`jobs_repo.start/finish/fail`, kinds `supplier_search` / `quote_ingest`), with
  the frontend polling a status endpoint.
- **Consequential actions** write `audit_repo.log(...)` and `events_repo.log(...)`.
- **Offline-first**: no `PROCUREAI_OPENAI_API_KEY` → clearly-flagged mocks, never
  silent fake data. `seed_demo_data` defaults to **false**
  ([config.py:38](apps/api/app/config.py:38)).

### 1.5 The price corpus we already own

| Model | File | Notes |
|---|---|---|
| `Quote` | models/quote.py | `line_items` JSON: `{name, qty, unitPrice, extended, leadDays}` + header `material_cost`/`freight`/`total`/`distance_miles` |
| `PurchaseDecision` | models/purchase_decision.py | which lines/suppliers actually won, with totals |
| `Document` | models/document.py | the BOM JSON |
| `Supplier` / `FoundSupplier` | models/supplier.py, found_supplier.py | network + discovered vendors |
| `SeedLineItemGroup`, `Comparison` | models/reference.py | global *seeded demo* data — not a price source |

**`quotes.line_items[].unitPrice` is the corpus.** Every ingested quote writes a
per-line unit price keyed by BOM line name; `purchase_decisions` tells us which
were accepted (an accepted price is a stronger market signal than a rejected
one). Quotes also carry `distance_miles` and `created_at`, so benchmarks can be
filtered by recency and, later, geography.

The only existing "budget" notion is
[`sample_data.budget_for()`](apps/api/app/services/quotes/sample_data.py:159) —
hardcoded demo figures (water $165k) surfaced as `LineComparison.budget`
([line_comparison.py:237](apps/api/app/services/quotes/line_comparison.py:237)).
This feature replaces it.

**Costing precedent**: [`finalize_quote`](apps/api/app/services/quotes/ingest.py:161)
does all arithmetic **in Python, never in the prompt** — a comment records model
arithmetic drifting ~$1 — and flags every derived figure in `notes`.
[`_qty_num`](apps/api/app/services/quotes/ingest.py:150) is the existing
`"1,682.7 LF" → 1682.7` parser.

### 1.6 Frontend

Single-file UI: [`apps/web/src/App.tsx`](apps/web/src/App.tsx) (~2.7k lines),
plus `model.ts` (decorates API data with styles) and `api.ts` (typed client).
Styling is `css('…')` strings on inline styles.

| Component | Line | Role |
|---|---|---|
| `ProjectWorkspace` | [1073](apps/web/src/App.tsx:1073) | tab bar |
| `TabOverview` | [1114](apps/web/src/App.tsx:1114) | metric cards + package progress |
| `ExtractedPanel` | [1463](apps/web/src/App.tsx:1463) | renders/edits the BOM `{n, q}` grid |
| `SupplierSearch` | [1587](apps/web/src/App.tsx:1587) | package picker + "what we're asking for" panel |
| `TabQuotes` | [2153](apps/web/src/App.tsx:2153) | quote table (amount / freight / total / lead) |
| `TabCompare` | [2262](apps/web/src/App.tsx:2262) | **line×supplier award grid** — already renders `$X/unit` per cell ([2395](apps/web/src/App.tsx:2395)) |

`TabCompare` is where this feature lands: the per-cell unit price is already on
screen, and a benchmark badge next to it is the whole product.

Data flow: `api.loadModelData(projectId)` fetches the workspace bundle in
parallel with per-fetch fallbacks; `buildModel()` decorates; components read
`m.*`. Tests: `App.test.tsx` (vitest + happy-dom, mocked fetch); backend
`apps/api/tests/` (pytest; `conftest.py` force-blanks all provider keys, so
**anything added must work fully offline**).

### 1.7 AI extraction flow

`registry.py` (data-driven `PlanTypeSpec`/`BomCategory`) + `plan_types.py` →
`service.py::extract_document`: text-first → per-sheet vision fallback →
consolidation → `_to_groups`. Runs in a subprocess (`isolated.py`). OpenAI calls
go through `vision.py::_parse` with **structured outputs**
(`client.beta.chat.completions.parse`, `temperature=0`, Pydantic
`response_format`). Orchestrated as a `BackgroundTask` in
[`_run_pipeline`](apps/api/app/api/routes/documents.py:459).

---

## 2. Where this feature should live

```
apps/api/app/
  models/price_benchmark.py       # aggregated stats, NOT org-scoped (§3.4)
  repositories/benchmarks.py
  schemas/benchmark.py
  services/benchmarking/
    __init__.py
    normalize.py     # material name → canonical key; unit normalization
    region.py        # project → (metro, state, division); ladder resolution
    data/metros.py   # static metro centroids + state→division map
    corpus.py        # harvest quote lines → observations
    aggregate.py     # observations → p25/median/p75 per region level
    verdict.py       # quoted price vs band → fair / high / low
  api/routes/benchmarks.py
migrations/versions/0019_price_benchmarks.py
migrations/versions/0020_project_region.py
```

Frontend: benchmark badges inside the existing `TabCompare` grid and `TabQuotes`
table — **no new tab in v1**. The pre-RFQ range is an additive panel in
`SupplierSearch`, which already shows the package BOM.

Reuse: `_line_items_for_package` moves out of `routes/sourcing.py` into a shared
service so sourcing and benchmarking agree on what a package contains.

---

## 3. Design

### 3.1 Numeric quantities (prerequisite)

Widen the persisted item shape, keeping `n`/`q` so nothing breaks:

```jsonc
{ "n": "12\" DI Pipe, Class 350", "q": "2,400 LF",
  "qty": 2400.0, "unit": "LF", "spec": "Class 350", "confidence": 0.82 }
```

`line_items` is a JSON column, so **no migration** — new keys are additive and
old rows simply lack them. `_to_groups` stops discarding fields; `LineItem`
(`schemas/document.py:63`) gains optional fields; the editor keeps editing
`n`/`q` and re-derives `qty`/`unit` on save via one shared parser
(`normalize.py`, generalized from `_qty_num`). Legacy rows parse `q` lazily on
read. Unparseable quantities are **unknown, never assumed to be 1**.

### 3.2 The corpus: quote lines → observations

One observation per priced quote line:

```
(canonical_material_key, unit, unit_price, quoted_at, accepted, org_id,
 supplier_id, metro, state, census_division, lat, lng, haul_miles)
```

Harvested from `quotes.line_items[]` where `unitPrice is not None`. Enrichment:
`accepted` from `purchase_decisions.selections`; `quoted_at` from
`quotes.created_at`; geography from **the quote's project** (the jobsite), not
the supplier — the buyer is asking "what should this cost delivered *here*", and
`quotes.distance_miles` already captures the supply-side leg separately.

Hygiene, all deterministic:

- **Canonical key** (`normalize.py`): lowercase, strip punctuation, normalize
  units and sizes (`12"` / `12 in` / `12 inch` → `12in`), map abbreviations
  (`DI` → `ductile iron`) via a hand-written alias table — the same approach
  [`packages._LABEL_ALIASES`](apps/api/app/services/sourcing/packages.py:248)
  already uses. Exact match on the canonical key only; **no fuzzy matching in
  v1** — a wrong match produces a confidently wrong verdict, which is worse than
  no verdict.
- **Unit agreement is mandatory.** Never convert LF↔EA↔TON. Units disagree →
  no benchmark for that line.
- **Outlier trim**: drop observations outside 3× the median before aggregating
  (typo'd quotes and lot-vs-unit confusion are common).
- **Recency window**: default 18 months, configurable in `config.py`; material
  prices move.
- **De-duplication**: one supplier quoting the same line across many RFQs should
  not dominate — cap contribution per (supplier, material) when aggregating.

### 3.3 Regionalization

**Assigning a region.** Projects already carry `loc` plus a cached `lat`/`lng`
geocode ([project.py:42](apps/api/app/models/project.py:42)), so no new
geocoding is needed. Resolve each project once and cache the result on the row
next to the existing `geocoded_loc`:

- `state` — parsed from `loc` (`"Raleigh, NC"` → `NC`) with the geocode as the
  authority when it disagrees. Works offline, which the test suite requires.
- `metro` — nearest metro/CBSA from a small static centroid table shipped in the
  repo (~400 rows, no API dependency, no licensing). A project farther than
  ~75 mi from any centroid has no metro and starts at the state level.
- `census_division` — derived from state via a static map (the nine Census
  divisions; construction cost indices are conventionally reported this way).

All three are cheap, deterministic, and offline-safe. No reverse-geocoding call,
so the mocked test path behaves identically to production.

**The tension.** Splitting the corpus by region multiplies the number of buckets
and divides the observations among them — exactly the wrong direction for the
k-anonymity floor in §3.4 and for cold start. A metro-level benchmark for a
specific fitting may never clear the floor.

**Resolution: a hierarchical ladder with explicit scope labelling.** Aggregate at
every level, then resolve a query by walking *up* until the floor is cleared:

| Level | Bucket | Label shown |
|---|---|---|
| 0 | metro | "typical in Raleigh–Durham" |
| 1 | state | "typical in NC" |
| 2 | census division | "typical in the South Atlantic" |
| 3 | national | "typical nationally" |

The response always reports which level it used and its sample size, so the buyer
sees a tight local band when the data supports one and an honest wide national
one when it doesn't. There is always *an* answer or a clean "not enough data" —
never a silent fallback that implies more locality than the data has.

**Derived regional index (M5).** Materials with deep regional coverage yield a
per-region price factor (that region's median ÷ national median, pooled across
well-covered materials). That factor can then adjust a *nationally*-benchmarked
thin material: "national data, adjusted for NC (+6%)". This extracts regional
signal from the materials that have it and lends it to the ones that don't —
self-contained, no licensed external index (RSMeans city cost indices would work
but cost money and add a dependency). Clearly labelled as adjusted, and never
counted as local data.

### 3.4 Cross-organization aggregation — the one architectural decision

The corpus is only useful pooled: a single customer's own history is too thin to
benchmark against on day one. But **every table in this codebase is org-scoped
by design**, and `quotes` holds customer-confidential pricing. Pooling is a
deliberate, consequential break from that pattern and must be built with
safeguards, not as an afterthought:

- `price_benchmarks` stores **only aggregates**, one row per
  `(canonical_key, unit, region_level, region_code)` — plus `n_obs`, `n_orgs`,
  `n_suppliers`, `p25`, `median`, `p75`, `updated_at`. No raw prices, no supplier
  names, no org ids, no project references. Deliberately absent from
  `SCOPED_TABLES` and written *only* by the rollup job, never by a request.
- **k-anonymity floor, scaled by geographic granularity.** Finer geography is
  more identifying: in a metro with three active contractors, a metro-level band
  narrows the field far more than a national one does. So the floor tightens as
  the ladder descends — start at metro 8 obs / 4 orgs / 4 suppliers, state
  6 / 3 / 3, division and national 5 / 3 / 3, all in `config.py`. A bucket below
  its floor is simply not published, and §3.3's ladder walks up to the next
  level. Combined with the §3.5 verdict rules, the API never returns a band it
  cannot stand behind.
- The org's **own** history is always usable with no floor and at any geographic
  level (it is their data), and is shown separately: "your past prices" vs
  "typical". This also makes the feature useful to a heavy single user before the
  pool is deep — and a repeat buyer in one metro is exactly the user whose own
  history is already regionally relevant.
- Rollup runs as a scheduled/background job into the aggregate table; requests
  never scan other tenants' quote rows. That is both a privacy boundary and the
  performance answer.
- **Flagged for a product/legal call before M2 ships**: pooling customer pricing
  into a shared benchmark needs to be covered by the ToS, and an org-level
  opt-out is the cheap insurance. If the answer is "no pooling", the feature
  degrades to own-history-only and §3.6's cold-start problem gets much worse —
  worth deciding early because it changes M2's scope, not its code.

### 3.5 The verdict

Given a quoted unit price and a published band, `verdict.py` returns a rating
plus the numbers behind it — never a bare label:

| Condition | Rating |
|---|---|
| ≤ p25 | `below` — "better than most" |
| p25 – p75 | `fair` — "in line" |
| p75 – 1.15 × p75 | `high` — "above typical" |
| > 1.15 × p75 | `well_above` — "well above typical" |
| no band / units disagree | `unknown` — "not enough data" |

Every response carries `median`, `p25`, `p75`, `sampleSize`, `windowMonths`, and
the **`regionLevel` + `regionLabel`** the band was drawn at, so the UI can always
show *why* and at what scope. Package- and quote-level verdicts roll up from
covered lines only, and always report **coverage** (benchmarked lines / total
lines) — a "fair" verdict covering 3 of 20 lines must not read as a clean bill
of health.

Deliberately **not** doing: a single "you're being overcharged by $X" headline.
The data won't support that precision, and one wrong accusation about a real
supplier relationship costs more than the feature is worth.

### 3.6 Cold start — be honest about it

On a fresh install there is no corpus, and `seed_demo_data` is off by default.
Regionalization compounds this: early on, almost every query will resolve at the
national level, and the honest UI consequence is that most bands start out
labelled "typical nationally" and tighten to metro-level as a market fills in.
That progression is a feature to communicate, not a defect to hide. The feature
must render "not enough data yet" cleanly rather than fabricate a band —
consistent with the repo's existing no-fake-data rule. Ways to shorten the
runway, in order of preference:

1. Ship the harvest job first so the corpus accumulates from real usage while the
   UI is still being built.
2. Backfill from historical quotes already in the database (the harvest job does
   this for free on first run).
3. AI-suggested reference prices for uncovered materials — **last resort**,
   clearly flagged `source: "ai"`, wide band, never counted toward coverage.
   Structured-output call following the `vision.py` pattern; returns nothing
   without an API key.

Published supplier pricing via web search was considered and rejected for v1:
wholesale construction materials are quoted, not listed, so the yield would be
low and the data poor.

### 3.7 API surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/projects/{id}/packages/{pkg}/benchmark` | per-line bands + verdicts for a package, aligned to the line-comparison grid |
| `GET` | `/api/quotes/{id}/benchmark` | verdict for one received quote (line + rollup) |
| `GET` | `/api/projects/{id}/packages/{pkg}/expected-cost` | pre-RFQ package range from the approved BOM |

Region is **implicit** — derived server-side from the project, never a client
parameter. That keeps the ladder logic in one place and means a client cannot
probe other regions' data by varying a query string. Every band echoes back its
`regionLevel`/`regionLabel` for display.

Numeric camelCase fields; display strings derived client-side, as in
`LineComparison`. If lookups prove slow, the aggregate table is already the fast
path — no new async machinery needed.

### 3.8 Closing the loop

Replace the hardcoded `budget_for` in `LineComparison.budget` with the
benchmarked expected cost, so `TabCompare` shows the award total against a real
reference. Every quote ingested thereafter feeds the corpus — the loop that
makes this compound.

---

## 4. Milestones

### M1 — Numeric quantities end to end
Carry `qty`/`unit`/`spec`/`confidence` through `_to_groups` into `line_items`;
`normalize.py` with the shared quantity parser + unit normalization
(LF/EA/SY/CY/TON/GAL, case- and plural-insensitive); extend `LineItem`; keep the
editor round-tripping. No data migration. Tests: table-driven parser cases,
extraction→persist→read round trip.

### M1b — Region resolution
Static metro-centroid and state→division tables in the repo; `region.py` to
resolve a project to `(metro, state, division)` from `loc` + cached `lat`/`lng`;
cache the result on the project row; backfill existing projects. Offline and
deterministic — no reverse-geocoding call. Tests: `"Raleigh, NC"` and geocode
disagreement, projects far from any centroid, missing/garbage `loc`.

### M2 — Corpus + regional aggregation (offline, deterministic)
`price_benchmarks` table + migration `0019`, keyed by
`(canonical_key, unit, region_level, region_code)`; `corpus.py` harvest (incl.
backfill of existing quotes); `aggregate.py` percentiles with trim, recency
window, per-supplier capping, and the granularity-scaled floor; rollup emits all
four levels in one pass; canonical-key alias table. Runs as a background job.
**No API exposure yet.** Tests: canonicalization, percentile math, floor
enforcement *per level*, ladder fallback, and an explicit test that the aggregate
table leaks no org/supplier identifiers.

### M3 — Verdicts + API
`verdict.py`, the ladder resolver, the three endpoints in §3.7,
own-history-vs-typical split, coverage + region-scope reporting,
`npm run gen:api`. Tests: full route coverage plus the cross-tenant 404 case
(see `tests/test_org_isolation.py`), "not enough data" paths, and a projects-in-
different-regions test proving two projects get different bands.

### M4 — Frontend
Benchmark badge in the `TabCompare` cell next to the existing `$X/unit`
([App.tsx:2395](apps/web/src/App.tsx:2395)); per-quote verdict in `TabQuotes`;
expected-cost range panel in `SupplierSearch`. Every band renders its region
label and sample size; coverage indicator wherever a rollup verdict appears.
Tests in `App.test.tsx` against mocked fetch, including the empty-corpus and
national-fallback states.

### M5 — Loop closure + fallbacks
Swap `LineComparison.budget` to the benchmarked expected cost; derived regional
index (§3.3) for nationally-benchmarked thin materials; AI fallback for uncovered
materials (flagged, excluded from coverage); weight accepted prices above
rejected ones in aggregation.

M1, M1b and M2 are the load-bearing work. M3–M4 are mechanical once the corpus
and the region ladder are sound.

---

## 5. Risks

- **Name matching is the whole ballgame.** `12" DI Pipe, Class 350` vs `12 inch
  ductile iron pipe cl350` must canonicalize identically, and two genuinely
  different materials must not. Exact-match-on-canonical-key plus a curated alias
  table keeps errors to *missing* benchmarks rather than *wrong* ones — the right
  failure direction. Always show what a band was matched from.
- **Cold start, multiplied by region.** Regionalization divides an already-thin
  corpus across four levels of buckets, so early queries resolve mostly at
  national scope. Mitigated by the §3.3 ladder (always an answer, honestly
  labelled), but the feature is weak until volume arrives in a given market.
  Plan the messaging accordingly rather than compensating with fabricated
  numbers.
- **Region assignment is only as good as `loc`.** It is a free-text field. A
  typo, a bare city with no state, or a multi-site project silently lands in the
  wrong bucket — and a wrong-region band is worse than a national one, because it
  looks specific. Resolution failures must fall back to national rather than
  guess, and the resolved region should be visible (and correctable) on the
  project.
- **Cross-tenant price leakage** is the highest-severity failure mode here — a
  benchmark that lets one customer infer a competitor's pricing, and regional
  granularity sharpens exactly that risk (a metro band in a thin market is close
  to naming names). §3.4's aggregate-only table, the granularity-scaled floor,
  and a dedicated leakage test are the controls.
- **Selection bias.** The corpus is quotes *we solicited* — skewed toward the
  suppliers our search surfaces and the regions our customers build in. It
  measures "typical for this platform", not "the market". Word the UI as
  "typical", never "market rate". Regional labelling makes this claim sound more
  authoritative than it is, which raises the bar on the wording rather than
  lowering it.
- **False precision.** Percentiles off 5 observations look authoritative and
  aren't. Always show sample size; never show a band below the floor.
- **Unit mismatch** silently produces 12× errors. Refuse rather than convert.
- **`documents.line_items` is unindexed JSON.** Fine at this scale; if
  benchmarking ever needs cross-project BOM queries, that is the point to
  normalize items into a real table — deliberately out of scope.

---

## 6. Decisions still open

1. **Pooling** (§3.4) — is cross-org aggregation acceptable under the ToS, and
   do orgs get an opt-out? Blocks M2's scope. Own-history-only is the fallback,
   and regionalization makes that fallback considerably weaker.
2. **Finest region level** — metro is assumed. Metro is what a buyer recognizes,
   but it is the hardest bucket to fill and the most identifying. Starting at
   state and adding metro once volume justifies it is the conservative
   alternative; the ladder supports either without rework.
3. **Recency window** — 18 months assumed; steel and copper move much faster
   than that. Possibly per-category rather than global.
4. **Freight** — benchmark material unit prices only (assumed), or delivered
   cost? Freight is quoted per-package, not per-line, so per-line delivered
   pricing isn't derivable from the current data. Since freight is largely what
   *makes* prices regional, excluding it means the bands understate real regional
   spread.
