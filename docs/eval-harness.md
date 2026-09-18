# Proq Eval Bench — accuracy harness for plan extraction

The bench measures how well `extract_document(path, plan_type)` reads a plan set,
against a labelled corpus. It exists so a prompt/spec/settings change can be
proven better rather than argued better.

**Scope (v1): BOM extraction accuracy only.** Timeline extraction, sheet
classification, and variance/cost tracking are deliberately out of scope — the
contracts below leave room for them but nothing implements them yet.

Three pieces, contracted here so they can be built in parallel:

| Piece | Lives in | Owns |
|---|---|---|
| Eval core | `apps/api/app/eval/` | corpus loading, scoring, variants, run execution, storage, CLI |
| Bench API | `apps/api/app/api/routes/bench.py`, `apps/api/app/schemas/bench.py` | HTTP surface over the core |
| Bench app | `apps/bench/` | the menu UI (Vite + React + TS, port 5185) |
| Corpus | `bench-corpus/` | plan PDFs, provenance, ground truth |

**These contracts are frozen.** If a piece needs a shape that differs from what
is written here, change this document first and say so — do not diverge silently,
because the other pieces are being built against it at the same time.

---

## 1. Corpus layout

Lives at repo root in `bench-corpus/`. PDFs are gitignored (large, and some
sources only permit local use); the manifest and ground truth ARE committed.

```
bench-corpus/
  manifest.json           # every corpus document (committed)
  docs/<doc_id>.pdf       # the plan set (gitignored)
  truth/<doc_id>.json     # ground-truth BOM (committed, optional per doc)
  variants/<id>.json      # tuning variants (committed)
```

### `manifest.json`

```json
{
  "version": 1,
  "documents": [
    {
      "id": "site-nc-greenway-01",
      "title": "Greenway Utilities Extension — Civil Set",
      "plan_type": "site",
      "file": "docs/site-nc-greenway-01.pdf",
      "source_url": "https://example.gov/plans/greenway.pdf",
      "source_name": "City of Example, NC — Public Works",
      "license": "public-domain-usgov",
      "retrieved_at": "2026-08-12",
      "sha256": "…",
      "bytes": 8123456,
      "pages": 34,
      "has_text_layer": true,
      "tags": ["utilities", "municipal", "vector-cad"],
      "truth": "truth/site-nc-greenway-01.json"
    }
  ]
}
```

- `id` — stable slug, `^[a-z0-9][a-z0-9-]*$`. Prefix with the plan type.
- `plan_type` — must be a key registered in `extraction.registry`. The real
  registered keys, with their category keys (truth items use these verbatim):

  | `plan_type` | categories |
  |---|---|
  | `site_plan` | `water`, `sewer`, `storm`, `erosion` |
  | `building_plan` | `concrete`, `rebar`, `steel`, `masonry`, `framing` |
  | `electrical_plan` | `raceway`, `conductors`, `equipment`, `devices`, `lighting`, `grounding`, `lowvoltage` |
  | `other` | — |

  This is the plan type the doc is *labelled for*; the bench can still run it
  under a different type. `python -m app.eval validate` enforces these keys.
- `truth` — `null` when the doc is unlabelled. Unlabelled docs are still useful
  (smoke/latency/crash coverage) and MUST load fine; they are simply skipped by
  accuracy metrics.
- `license` — one of `public-domain-usgov`, `public-domain`, `cc-by`, `cc-by-sa`,
  `permissive-other`, `local-only`. Anything not clearly redistributable is
  `local-only` and its PDF is never committed.
- `sha256` — of the PDF, so a corpus drift is detectable.

### `truth/<doc_id>.json`

```json
{
  "doc_id": "site-nc-greenway-01",
  "plan_type": "site",
  "authored_by": "agent:corpus-acquisition",
  "authored_at": "2026-08-12",
  "completeness": "full",
  "notes": "Quantities taken from the C-4 utility summary table.",
  "items": [
    {
      "category": "water",
      "name": "12\" DI Pipe, Class 350",
      "aliases": ["12 inch ductile iron pipe", "12\" ductile iron waterline"],
      "quantity": 1450,
      "unit": "LF",
      "qty_tolerance": 0.05,
      "required": true,
      "source": "Sheet C-4, utility summary"
    }
  ],
  "forbidden": [
    { "name": "silt fence", "why": "legend symbol only — not installed on this set" }
  ]
}
```

- `completeness` — `full` (every material on the set is listed) or `partial`
  (only the listed items are verified). **Precision is only scored on `full`
  docs**; on `partial` docs an extracted item with no truth match is `unknown`,
  not a false positive, because the truth simply may not cover it.
- `qty_tolerance` — fractional tolerance, default `0.05`. Use a wider tolerance
  for genuinely estimated quantities (symbol counts on dense sheets).
- `required: false` — a "nice to have" item. Missing it does not count against
  recall; finding it counts as a bonus (reported separately as `optional_recall`).
- `forbidden` — items the model is known to hallucinate here (legend symbols,
  design alternates, notes-only minimums). Any match is a hard error.
- `unit: null` / `quantity: null` — that field is simply not scored for the item.

---

## 2. Eval core — `apps/api/app/eval/`

Pure Python, no FastAPI imports. Importable from the CLI, the API, and pytest.

> **Python 3.8 compatibility is mandatory.** `pyproject.toml` says
> `requires-python = ">=3.8"` and the local venv is 3.8.3 (Railway runs 3.11).
> The signatures below are written as `str | None` for readability only — in
> code use `typing.Optional[str]`, `typing.List[...]`, `typing.Dict[...]`.
> PEP 604 unions and PEP 585 builtin generics evaluate at runtime in dataclass
> and Pydantic annotations and **will crash on 3.8**. Verify with
> `apps/api/.venv/bin/python`, not the system `python3`.

```
apps/api/app/eval/
  __init__.py
  corpus.py     # load/validate manifest + truth
  scoring.py    # match extracted vs truth → metrics
  variants.py   # variant definition + apply() context manager
  runner.py     # execute a run (docs × variants × trials)
  store.py      # SQLite persistence of runs/trials
  __main__.py   # CLI: python -m app.eval …
```

### `corpus.py`

```python
@dataclass(frozen=True)
class CorpusDoc:
    id: str
    title: str
    plan_type: str
    path: str            # ABSOLUTE path to the PDF
    exists: bool         # False when the gitignored PDF is not on this machine
    source_url: str | None
    source_name: str | None
    license: str
    retrieved_at: str | None
    sha256: str | None
    bytes: int | None
    pages: int | None
    has_text_layer: bool | None
    tags: list[str]
    has_truth: bool

@dataclass(frozen=True)
class TruthItem:
    category: str
    name: str
    aliases: list[str]
    quantity: float | None
    unit: str | None
    qty_tolerance: float
    required: bool
    source: str | None

@dataclass(frozen=True)
class Truth:
    doc_id: str
    plan_type: str
    completeness: str          # "full" | "partial"
    notes: str | None
    items: list[TruthItem]
    forbidden: list[dict]      # {"name": str, "why": str}

def corpus_dir() -> str: ...
def load_corpus() -> list[CorpusDoc]: ...
def get_doc(doc_id: str) -> CorpusDoc: ...        # raises KeyError
def load_truth(doc_id: str) -> Truth | None: ...
def validate_corpus() -> list[str]: ...           # human-readable problems, empty = clean
```

`load_corpus()` must never raise on a missing PDF — it sets `exists=False`. It
raises only on a malformed/absent manifest.

### `scoring.py`

The core problem is **matching** an extracted item to a truth item. Deterministic
by default; an optional LLM judge is a flag, never the default.

```python
@dataclass(frozen=True)
class ExtractedRef:                # the index space ItemMatch.extracted_index refers to
    index: int
    name: str
    quantity: float | None
    unit: str | None
    category: str | None           # resolved from the group label via the spec
    group: str

@dataclass(frozen=True)
class ItemMatch:
    truth_index: int | None       # None → extracted item with no truth counterpart
    extracted_index: int | None   # None → truth item that was missed
    score: float                  # 0..1 name similarity that produced the match
    category_ok: bool
    quantity_ok: bool | None      # None when truth has no quantity
    unit_ok: bool | None
    kind: str  # "hit" | "miss" | "extra" | "unknown" | "forbidden"
    # Carried alongside the indices so a STORED score renders on its own. Each
    # is populated only where the fact exists at match time — never synthesised.
    truth_name: str | None
    extracted_name: str | None
    quantity_got: float | None
    quantity_want: float | None
    unit_got: str | None
    unit_want: str | None
    required: bool
    truth_source: str | None        # truth's `source` — where to look to confirm a miss
    qty_tolerance: float | None     # the tolerance governing this item
    forbidden_why: str | None       # kind="forbidden" only: why it is a known hallucination
    truth_category: str | None      # the two sides of `category_ok`, so the UI can
    extracted_category: str | None  # show "sewer → water" instead of just "wrong"

@dataclass(frozen=True)
class DocScore:
    doc_id: str
    plan_type: str
    precision: float | None       # None on partial-completeness truth
    recall: float | None          # None when the truth has no required items
    f1: float | None
    optional_recall: float | None
    quantity_accuracy: float | None   # among hits with a truth quantity
    unit_accuracy: float | None
    category_accuracy: float | None   # among hits; None when there are none
    hallucinations: int               # forbidden matches
    counts: dict                      # {"hit","miss","extra","unknown","forbidden","truth_total","truth_required","extracted_total"}
    matches: list[ItemMatch]
    def to_dict(self) -> dict: ...    # what store.bench_trial.score holds

def flatten_extracted(extracted_groups: list[dict], spec=None) -> list[ExtractedRef]: ...
def dimensional_numbers(name: str) -> dict[str, int]: ...  # {number: count} that gate
def code_values(name: str) -> dict[str, set]: ...          # {code key: values} that only conflict
def gate_ok(truth_name: str, extracted_name: str) -> bool: ...
def name_similarity(truth_name: str, extracted_name: str) -> float: ...  # DIRECTIONAL, raw names
def score_document(extracted_groups: list[dict], truth: Truth, spec=None) -> DocScore: ...
def aggregate(scores: list[DocScore]) -> dict: ...   # macro-averaged run summary
```

Matching rules, in order:

1. **Normalise** both names: lowercase, expand `"` → ` inch `, collapse
   whitespace/punctuation, strip trailing parentheticals, singularise trivial
   plurals. Keep the numbers — `12" pipe` must not match `8" pipe`.
2. **Exact match** on normalised name or any normalised alias → score 1.0.
3. **Fuzzy match** — token-set ratio (rapidfuzz if available, else difflib),
   accepted at ≥ 0.82, behind the **dimensional gate**. Size is the single most
   load-bearing token in a BOM and fuzzy matchers routinely collapse `4"` into
   `6"`, so a number can veto a match — but only if it is the kind of number
   that means a size. A numeral plays one of three roles:

   | Role | Examples | Gates? |
   |---|---|---|
   | dimension / spec value | `4"`, `Schedule 40`, `Class 350`, `12 AWG`, `480V` | **yes** |
   | catalogue / model code | `JEBL-30000LM-GL-120V-40K-80CRI`, `IP65` | no |
   | equipment tag | `ATS1`, `MTS1`, `MH-3`, `P-2` | no |

   A numeral is a dimension when it stands alone (`4`, `Schedule 40`) or is glued
   to a unit (`12awg`, `480v`); it is a code when it sits inside a hyphenated
   model number, follows letters with no separator (`ATS1`, `IP65`, `C900`), or
   is glued to a non-unit suffix (`30000lm`, `80cri`, `40k`). The role is read
   from the RAW name — normalisation dissolves the hyphens that tell `MH-3`
   (a tag) from `3` (a size).

   The gate then has two halves:

   - **Presence, directional** — every dimension the truth states must appear in
     the extracted name, counted (so `8"x8"` is not satisfied by `8"x6"`). The
     converse does not hold: extra spec detail on the extracted side
     (`IP65, Duracoat Finish`) is not a contradiction. Detail the truth states
     and the extraction dropped IS one — `PVC Conduit` has not found
     `2" Schedule 40 PVC Conduit`, it has found something vaguer.
   - **Contradiction, keyed** — a code or unit-bearing value that appears on
     BOTH sides with disjoint values blocks the match: `MH-3` vs `MH-4`,
     `30000LM` vs `20000LM`, `600A` vs `800A`. A code present on one side only
     never blocks. This check runs against everything the truth ITEM states
     (name and aliases together), because truth files carry short aliases like
     `MSB` and token-set similarity scores a bare acronym against any name
     containing it at 1.0 — without it, an alias would carry a match its own
     item contradicts.

   Treating all three roles alike is what made the first live run report a
   correctly-found fixture as BOTH a miss and an extra, understating recall on
   a 2-document electrical run by roughly a third.
4. Matching is **global and greedy by descending score**, one-to-one — a truth
   item is consumed by at most one extracted item.
5. `category_ok` is recorded but does NOT gate a match: a right item in the wrong
   category is a hit with `category_ok=False`, which is a different (smaller)
   failure than not finding it.

Metric definitions:

- `recall` = hits / required truth items
- `precision` = hits / (hits + extra), **only on `completeness == "full"`**
- `quantity_ok` = `abs(got - want) <= want * qty_tolerance`; unit-normalise
  first (`LF`/`FT`/`FEET` are the same; `EA`/`EACH`; `SY`/`SQYD`; `CY`; `TON`).
- `forbidden` beats everything: an extracted item matching a forbidden entry is
  `kind="forbidden"` and never also an `extra`.

Every metric must be `None` rather than `0.0` when it is undefined. A zero and an
unmeasurable are different facts and the UI shows them differently.

### `variants.py`

A variant is an overlay on the live extraction config, applied as a context
manager and fully restored afterwards. This is the tuning surface — one variant
per hypothesis, diffable in git.

```json
{
  "id": "text-first-strict",
  "label": "Text-first, stricter escalation",
  "description": "Raise the text-pass floor so thin text results escalate to vision.",
  "settings": { "text_pass_min_items": 8, "vision_tile_cols": 4 },
  "prompts": { "SYSTEM_PROMPT": "…", "CONSOLIDATION_SYSTEM_PROMPT": "…" },
  "spec_overrides": {
    "site": {
      "prompt_guidance": "…",
      "prefer_vision": false,
      "categories": { "water": { "description": "…", "examples": ["…"] } }
    }
  }
}
```

```python
@dataclass(frozen=True)
class Variant:
    id: str
    label: str
    description: str | None
    settings: dict
    prompts: dict
    spec_overrides: dict

def load_variants() -> list[Variant]: ...          # baseline first; never raises
def get_variant(vid: str) -> Variant: ...          # KeyError when unknown
def validate_variant(v: Variant) -> list[str]: ... # what apply() would reject

@contextmanager
def apply(variant: Variant): ...
```

An unknown setting, prompt constant, plan type, category, or spec field is a
hard error, not a silent no-op — a variant that quietly does nothing would show
up as "no measurable difference" and be believed. `validate_variant()` reports
the same problems without applying anything, so the runner refuses an invalid
variant *before* spending a model call on it.

`prompts` can only override module-level string constants of
`extraction.prompts` — today `SYSTEM_PROMPT`, `CONSOLIDATION_SYSTEM_PROMPT`, and
`TIMELINE_SYSTEM_PROMPT`. The `build_*` helpers read those globals at call time,
so the overlay reaches the model. A prompt built from a literal inside a
function is NOT overridable: lift it to a module constant first.

`apply()` patches `app.config.settings` attributes, `app.services.extraction.prompts`
module constants, and deep-copies + mutates registry specs — then restores all
three in a `finally`, including on exception. `id == "baseline"` is reserved: it
is the empty overlay and must always exist (synthesised if no file defines it).

`apply()` is **not** thread-safe — it mutates process-global config. The runner
must serialise variant application (see below).

### `store.py`

Its own SQLite file, separate from the product DB — eval data must never touch
`procureai.db`. Path from `settings.bench_db_url`.

Tables: `bench_run` and `bench_trial`.

```
bench_run:   id (uuid str), created_at, finished_at, status, variant_id,
             plan_type, doc_ids (json), trials, notes,
             progress_done, progress_total, error, summary (json)
bench_trial: id, run_id, doc_id, variant_id, trial_index, status,
             started_at, finished_at, latency_ms, error,
             groups (json — raw ExtractionResult.groups),
             summary_text, mocked, score (json — DocScore)
```

`status` ∈ `queued | running | done | failed | cancelled`.

```python
def create_run(*, variant_ids, doc_ids, plan_type, trials, notes) -> list[str]  # one run per variant
def get_run(run_id) -> dict | None          # includes "trials_detail": list[dict]
def list_trials(run_id) -> list[dict]
def list_runs(limit=50) -> list[dict]       # summary rows only
def delete_run(run_id) -> bool
def cancel_run(run_id) -> bool
def run_status(run_id) -> str | None        # cheap poll, used by the runner
def start_run(run_id, total) -> None
def append_trial(run_id, trial: dict) -> None
def update_progress(run_id, done, total) -> None
def finish_run(run_id, *, status, summary, error=None) -> None
def reset_engine() -> None                  # tests repointing bench_db_url
```

`bench_trial` also carries `seq` — insertion order within the run, because
several trials can start inside the same second and the detail view must list
them in the order they actually ran.

One run row per (variant × the doc set). Selecting 2 variants in the UI creates
2 runs sharing a `notes`/batch label — the compare view is then run-vs-run.

### `runner.py`

```python
def execute_run(run_id: str, *, on_progress=None) -> dict
```

- Serial across variants (config is global), parallel-free within a doc — the
  extraction pipeline already parallelises sheets internally and each in-flight
  sheet holds rendered tiles in memory. Do not add a second layer of concurrency.
- Each trial: `with variants.apply(v): ExtractionResult = extract_document(...)`,
  timed; then `score_document` if truth exists.
- A trial that raises is recorded `status="failed"` with the error and the run
  continues. Only an unrecoverable error fails the run.
- Honours cancellation: check the run's status between trials and stop cleanly.
- `mocked=True` results (no `PROCUREAI_OPENAI_API_KEY`) are recorded and flagged.
  **Scores from mocked trials are meaningless and must be marked as such**, never
  silently averaged into a summary.

The summary stored on the run (and returned by `execute_run`):

```python
{
  "variant_id": str,
  "trials_total": int, "trials_run": int, "trials_ok": int, "trials_failed": int,
  "trials_mocked": int, "trials_unlabelled": int, "trials_scored": int,
  "mocked": bool,               # ANY trial came from the mock path — surface it
  "latency_ms_avg": float | None,
  "metrics": dict | None,       # aggregate() over LIVE, labelled trials only
  "mocked_metrics": dict | None,# aggregate() over mocked trials, kept apart
  "note": str | None,           # why `metrics` is None, when it is
}
```

### CLI — `python -m app.eval`

```bash
python -m app.eval corpus                      # list corpus + truth coverage
python -m app.eval validate                    # validate manifest + truth files
python -m app.eval variants                    # list variants
python -m app.eval run --docs a,b --variant baseline --trials 1
python -m app.eval runs                        # recent runs + headline metrics
python -m app.eval show <run_id>               # per-doc detail, miss/extra lists
python -m app.eval compare <run_id> <run_id>   # metric deltas
```

Human-readable by default; `--json` on every subcommand for machine use.

`corpus`, `validate`, and `variants` all run on a machine with NO corpus (the
PDFs are gitignored and the manifest lands with the corpus track): they print
what is missing and exit 0. `validate` exits 1 only when a corpus that does
exist has problems — "not built yet" is not a validation failure.

### Deviations from the sketch above (Track A, as built)

The signatures in this section were adjusted where the sketch could not be
implemented as written. Everything else matches.

1. **`create_run() -> list[str]`**, not `str`. A run row is per-variant ("one run
   row per variant × the doc set") while the parameter is `variant_ids`, so a
   single id could not be returned. It returns one id per variant, in order,
   which is exactly what `POST /bench/runs → {run_ids: []}` needs.
2. **`DocScore.recall` and `category_accuracy` are `float | None`.** The sketch
   typed them non-optional, which contradicts "an undefined metric is None":
   recall is undefined when the truth has no required items, category accuracy
   when there are no hits.
3. **`ItemMatch` carries the names, the got/want quantities and units, the
   truth's `source` and `qty_tolerance`, the forbidden entry's `why`, and both
   categories** in addition to the indices. The score is persisted as JSON and
   rendered later; without these every consumer would have to re-run the
   flattening and re-read the truth file to explain a single failed row. Each
   field is populated only where it exists — an `extra` has no truth
   counterpart, so its truth-side fields are None rather than a placeholder.
4. **`flatten_extracted()` is public** and defines the index space
   `extracted_index` refers to (group order, then item order — the order
   `extraction.service._to_groups` emits). Consumers must not invent their own.
5. **`score_document(..., spec=None)`** — spec defaults to None, in which case
   `category_ok` rests on whatever the groups themselves declare. Tests and
   ad-hoc scoring do not need a registry lookup.
6. **`get_run()` includes `trials_detail`**, and `list_trials`, `run_status`,
   `start_run`, `reset_engine`, `stats` are additional store helpers.
7. **`validate_corpus()` never raises**; an absent manifest comes back as the
   single problem "corpus not populated". `load_corpus()` / `load_truth()` still
   raise `corpus.CorpusError` for a missing or malformed manifest.
8. Plan-type keys in the registry are `site_plan`, `building_plan`,
   `electrical_plan`, `other` — the §1 example's `site` is illustrative only.
   Manifest `plan_type` values must be real registry keys; `validate` enforces it.

---

## 3. Bench API — `/bench/*`

Dev-only, **unauthenticated**, mounted only when `settings.bench_enabled`
(default: true when `env != "production"`, always false in production). This is a
local tuning tool; it is never exposed publicly. `apps/api/app/main.py` already
mounts the stub router — fill it in, don't re-wire it.

Schemas live in `apps/api/app/schemas/bench.py` (Pydantic v2), so the generated
OpenAPI types are usable by the bench app via `npm run gen:api`.

| Method | Path | Returns |
|---|---|---|
| GET | `/bench/status` | `{enabled, corpus_dir, docs, labelled, live_extraction}` — `live_extraction=false` means no OpenAI key, results will be mocked |
| GET | `/bench/corpus` | `{documents: CorpusDocOut[], problems: string[]}` |
| GET | `/bench/plan-types` | `[{key, label, description, enabled, categories:[{key,label,tone}]}]` |
| GET | `/bench/variants` | `VariantOut[]` |
| POST | `/bench/runs` | body `{doc_ids[], variant_ids[], plan_type?, trials=1, notes?}` → `202 {run_ids: string[], extractions, docs, variants, trials}`; queues execution in the background |
| GET | `/bench/runs?limit=` | `RunSummaryOut[]`, newest first |
| GET | `/bench/runs/{id}` | `RunDetailOut` — run + trials + per-doc scores + match lists |
| POST | `/bench/runs/{id}/cancel` | `{cancelled: bool}` |
| DELETE | `/bench/runs/{id}` | `{deleted: bool}` |
| GET | `/bench/runs/compare?a=&b=` | `{a: RunSummaryOut, b: RunSummaryOut, deltas: {...}, per_doc: [...], mocked}` |

Runs execute on a background thread, **serialised through a single worker**. A
plan set takes minutes, so the POST must return immediately — but `apply()`
mutates process-global config, so two runs executing concurrently would silently
corrupt each other's overlay and produce results that look real and are garbage.
One worker thread drains a FIFO queue; a run waiting behind another honestly
reports `status="queued"` until the worker reaches it. The bench app polls
`GET /bench/runs/{id}` every ~2s; no SSE.

`plan_type` omitted → each doc runs under its manifest `plan_type`.

Every response model must be explicit about undefined metrics: `float | None`,
never a `0.0` placeholder.

### Deviations from the sketch above (Track B, as built)

1. **`POST /bench/runs` returns 202**, and its body carries the cost alongside
   the ids: `extractions` (= `docs × variants × trials`), plus `docs`,
   `variants`, `trials`. §6 requires the UI to state what a run will cost, and
   the server is the only place that number can be authoritative.
2. **Duplicate `doc_ids`/`variant_ids` are de-duplicated** (order preserved). A
   repeated id is a repeated model call, never an intentional one.
3. **Refusals happen before anything is created.** No documents → 400; no
   variants → 400; unregistered `plan_type` → 400; a variant with
   `validate_variant()` problems → 400 (checked up front so an invalid overlay
   costs nothing); unknown document or unknown variant → 404; `trials` outside
   1..20 → 422. Nothing is written to the store on any of these.
4. **`/bench/runs/compare` is declared before `/bench/runs/{id}`**, otherwise
   FastAPI captures `compare` as a run id.
5. **`per_doc` carries the full `DocScoreOut` for each side**, not just metrics:
   `[{doc_id, a: DocScoreOut|null, b: DocScoreOut|null, mocked, trials_a,
   trials_b}]`. The item-level lists are what say which materials a variant
   fixed. Each side is the document's first **live, scored** trial in that run;
   `null` when the run produced none (unlabelled, failed, or mocked-only).
   Mocked trials never appear as a score, only as `mocked: true`.
6. **`RunSummaryOut.mocked_trials`** is lifted out of `summary` so the runs list
   can badge MOCKED without fetching every run's detail. `null` until the run
   has a summary — "not known yet" is a different claim from "zero mocked".
7. **`DocScoreOut.completeness`** (`"full" | "partial" | null`) is resolved from
   the truth file at render time; the stored score does not carry it. It is what
   explains a null precision (on partial truth, precision is deliberately
   unmeasurable rather than zero).
8. **`RunDetailOut.trials_detail`** — the trial rows keep the key
   `store.get_run()` already uses. Trial `id`s are persisted, so they are stable
   across polls.
9. **`MatchOut` passes through the optional `ItemMatch` enrichment**
   (`truth_category`, `extracted_category`, `truth_source`, `qty_tolerance`,
   `forbidden_why`) when present and reports `null` when absent — those fields
   belong to `app.eval.scoring`, which the API consumes rather than owns.
10. **`/bench/status` adds `present` and `populated`**; `/bench/variants` adds
    `problems` per variant. Both feed the empty/disabled states: "PDFs not on
    this machine" and "this variant would be rejected" are the two things the UI
    otherwise has to guess. `corpus_dir` is the ABSOLUTE resolved path, not the
    raw (possibly relative) setting.
11. **An unpopulated corpus is a 200 with an empty list**, on every read
    endpoint — `/bench/corpus` reports the reason in `problems`. Only a run
    request against a corpus that cannot be loaded is an error (404).

---

## 4. Bench app — `apps/bench/`

`@proq/bench`, Vite + React 18 + TS, port **5185**, `VITE_BENCH_API_URL`
(default `http://localhost:8040`). Mirror `apps/web`'s setup: plain CSS variables
and inline styles, no component library, no router dependency — this is a tool,
not a product surface. It is a workspace app so `npm install` at the root covers
it; add `dev:bench` to the root `package.json` scripts.

Four panels, matching the agreed layout:

```
┌─ Corpus ──────────┬─ Run ───────────────┐
│ ☑ site-plan-01    │ plan type: site     │
│ ☑ elec-04         │ variant: promptsv2  │
│ ☐ bldg-12         │ trials: 5  [Run]    │
├─ Results ─────────┴─────────────────────┤
│ precision .82  recall .74  F1 .78       │
│ elec-04  ✗ missing: 200A panel (x2)     │
└─────────────────────────────────────────┘
```

- **Corpus** — checkbox list, filter by plan type / labelled-only, badges for
  "no truth" and "PDF missing locally". Select-all per plan type.
- **Run** — plan type override, multi-select variants, trial count, Run button.
  Disabled with an explanation when `live_extraction` is false or nothing is
  selected. Shows live progress (`done/total`) and a Cancel button while running.
- **Results** — headline metrics for the selected run, then per-document rows
  expanding into the concrete diff: **misses** (in truth, not extracted),
  **extras** (extracted, no truth match), **wrong quantity** (matched, quantity
  outside tolerance, showing got vs want), **hallucinations** (forbidden hits).
  The diff is the whole point of the tool — it is what tells you what to fix.
- **Compare** — pick two runs, show metric deltas with direction, and which
  documents moved. This is how a variant is judged better.

Non-negotiables:

- Show a `MOCKED` banner when results came from the mock path. Never present a
  mock number as an accuracy result.
- Render an undefined metric as `—`, never `0.00`.
- No fake/placeholder data anywhere — empty states say what is missing and how
  to fix it (see the project's no-placeholder-data rule).

---

## 5. Ports & processes

| Process | Port | Command |
|---|---|---|
| Bench API | 8040 | `cd apps/api && PYTHONPATH=. .venv/bin/python -m uvicorn app.main:app --port 8040` |
| Bench app | 5185 | `npm run dev --workspace @proq/bench -- --port 5185 --strictPort` |

`launch.json` configs `bench-api` and `bench-web` are already registered.

## 6. Cost discipline

A bench run makes real model calls against real plan sets. Every piece must
respect this:

- Trials default to **1**, never higher by default.
- The UI states the number of extractions a run will perform before it starts
  (`docs × variants × trials`).
- Nothing auto-runs on load, on save, or on a file change.
- `python -m app.eval run` with no `--docs` is an error, not "run everything".
