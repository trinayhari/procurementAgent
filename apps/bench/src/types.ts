// Wire types for `/bench/*` — the frozen contract in docs/eval-harness.md §3,
// with the dataclasses of §2 as the shape of their nested payloads.
//
// These are hand-written rather than generated (`npm run gen:api` only emits
// apps/web/src/api-types.ts) because Track C builds ahead of the API. When
// apps/api/app/schemas/bench.py lands, this file is what it must agree with;
// everything marked OPTIONAL below is an addition the UI needs and the frozen
// document did not pin down (see the notes on ItemMatchOut and CompareOut).

export type RunStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
export type MatchKind = 'hit' | 'miss' | 'extra' | 'unknown' | 'forbidden'

// GET /bench/status
export type StatusOut = {
  enabled: boolean
  corpus_dir: string
  docs: number
  labelled: number
  /** false → no OpenAI key; every extraction would be mocked, so no run can produce a real number. */
  live_extraction: boolean
}

// GET /bench/corpus
export type CorpusDocOut = {
  id: string
  title: string
  plan_type: string
  path: string
  /** false → the gitignored PDF is not on this machine; the doc cannot be run. */
  exists: boolean
  source_url: string | null
  source_name: string | null
  license: string
  retrieved_at: string | null
  sha256: string | null
  bytes: number | null
  pages: number | null
  has_text_layer: boolean | null
  tags: string[]
  has_truth: boolean
}

export type CorpusOut = {
  documents: CorpusDocOut[]
  /** Human-readable manifest/truth problems from validate_corpus(). */
  problems: string[]
}

// GET /bench/plan-types
export type PlanTypeOut = {
  key: string
  label: string
  description: string | null
  enabled: boolean
  categories: { key: string; label: string; tone: string }[]
}

// GET /bench/variants
export type VariantOut = {
  id: string
  label: string
  description: string | null
  settings: Record<string, unknown>
  prompts: Record<string, string>
  spec_overrides: Record<string, unknown>
}

// POST /bench/runs
export type CreateRunBody = {
  doc_ids: string[]
  variant_ids: string[]
  plan_type?: string | null
  trials: number
  notes?: string | null
}
export type CreateRunOut = { run_ids: string[] }

// One extracted BOM group, straight off ExtractionResult.groups. `q` is a
// display string ("1,450 LF" or "—"), not a number — see
// apps/api/app/services/extraction/service.py::_to_groups.
export type ExtractedGroup = {
  group: string
  count: number
  tone?: string
  items: { n: string; q: string }[]
}

// scoring.ItemMatch, as Track A landed it: the match carries the item names and
// the got/want pairs directly, so the diff renders from the match list alone —
// indices are never resolved client-side (truth items are not served by any
// endpoint, and `groups[].items[].q` is a formatted string, not a number).
export type ItemMatchOut = {
  truth_index: number | null
  extracted_index: number | null
  score: number
  category_ok: boolean
  quantity_ok: boolean | null
  unit_ok: boolean | null
  kind: MatchKind

  /** Truth-side item name — present on hit / miss / (forbidden, as the forbidden entry). */
  truth_name?: string | null
  /** Extraction-side item name — present on hit / extra / unknown / forbidden. */
  extracted_name?: string | null

  quantity_got?: number | null
  quantity_want?: number | null
  unit_got?: string | null
  unit_want?: string | null
  /** false → a "nice to have" truth item; missing it does not count against recall. */
  required?: boolean | null

  // Not part of Track A's confirmed set; rendered only when the API sends them.
  truth_category?: string | null
  extracted_category?: string | null
  truth_source?: string | null
  /** Fractional tolerance the quantity was judged against (truth default 0.05). */
  qty_tolerance?: number | null
  /** Raw display quantity as the pipeline emitted it, when there is no numeric parse. */
  extracted_display?: string | null
  /** For kind="forbidden": the truth file's reason this item is a known hallucination. */
  forbidden_why?: string | null
}

export type ScoreCounts = {
  hit: number
  miss: number
  extra: number
  unknown: number
  forbidden: number
  truth_total: number
  extracted_total: number
}

// scoring.DocScore
export type DocScoreOut = {
  doc_id: string
  plan_type: string
  /** null on partial-completeness truth — an unmatched extra may simply be unlabelled. */
  precision: number | null
  recall: number | null
  f1: number | null
  optional_recall: number | null
  quantity_accuracy: number | null
  unit_accuracy: number | null
  category_accuracy: number | null
  /** required items found with quantity and unit right — RFQ-ready share; null when unmeasurable */
  usable_recall: number | null
  hallucinations: number
  counts: ScoreCounts
  matches: ItemMatchOut[]
  /** OPTIONAL: "full" | "partial" — the UI explains `extra` vs `unknown` with it. */
  completeness?: string | null
}

// store.bench_trial
export type TrialOut = {
  id: string
  run_id: string
  doc_id: string
  variant_id: string
  trial_index: number
  status: RunStatus
  started_at: string | null
  finished_at: string | null
  latency_ms: number | null
  error: string | null
  groups: ExtractedGroup[] | null
  summary_text: string | null
  /** true → no OpenAI key at run time; the numbers are fixtures, not accuracy. */
  mocked: boolean
  score: DocScoreOut | null
}

// scoring.aggregate() — macro-averaged over the run's scored documents.
// A metric is null when it was undefined for EVERY scored doc (e.g. precision when
// no doc had full-completeness truth); `defined` says how many docs backed each one.
export type RunMetrics = {
  documents: number | null
  precision: number | null
  recall: number | null
  f1: number | null
  optional_recall: number | null
  quantity_accuracy: number | null
  unit_accuracy: number | null
  category_accuracy: number | null
  /** required items found with quantity and unit right — RFQ-ready share; null when unmeasurable */
  usable_recall: number | null
  hallucinations: number | null
  defined?: Partial<Record<MetricKey | 'hallucinations', number>> | null
  counts?: Partial<ScoreCounts> | null
}

// runner's per-run summary. The metrics are NESTED under `metrics`, and mocked
// trials are aggregated separately into `mocked_metrics` — a mocked number is not
// an accuracy result, so the two must never be read from the same place.
export type RunSummary = {
  variant_id: string
  trials_total: number
  trials_run: number
  trials_ok: number
  trials_failed: number
  trials_mocked: number
  trials_unlabelled: number
  trials_scored: number
  mocked: boolean
  latency_ms_avg: number | null
  metrics: RunMetrics | null
  mocked_metrics: RunMetrics | null
  note: string | null
}

// store.bench_run
export type RunSummaryOut = {
  id: string
  created_at: string
  finished_at: string | null
  status: RunStatus
  variant_id: string
  plan_type: string | null
  doc_ids: string[]
  trials: number
  notes: string | null
  progress_done: number
  progress_total: number
  error: string | null
  summary: RunSummary | null
  /** Row-level, so the runs list can badge MOCKED without fetching each run's
   *  detail. null = not known yet (no summary), which is NOT the same as zero. */
  mocked_trials: number | null
}

// GET /bench/runs/{id}
export type RunDetailOut = RunSummaryOut & { trials_detail: TrialOut[] }

// GET /bench/runs/compare?a=&b=
//
// The contract writes `deltas: {...}` and `per_doc: [...]` without pinning the
// members. The UI computes its headline deltas from `a.summary`/`b.summary`
// (always well-defined) and only reads `per_doc` for the which-documents-moved
// table, in the shape below.
export type PerDocCompareOut = {
  doc_id: string
  a: DocScoreOut | null
  b: DocScoreOut | null
}

export type CompareOut = {
  a: RunSummaryOut
  b: RunSummaryOut
  deltas: Record<string, number | null>
  per_doc: PerDocCompareOut[]
}

export type MetricKey =
  | 'precision' | 'recall' | 'f1' | 'optional_recall'
  | 'quantity_accuracy' | 'unit_accuracy' | 'category_accuracy' | 'usable_recall'

export const METRIC_LABELS: Record<MetricKey, string> = {
  precision: 'Precision',
  recall: 'Recall',
  f1: 'F1',
  optional_recall: 'Optional recall',
  quantity_accuracy: 'Quantity',
  unit_accuracy: 'Unit',
  category_accuracy: 'Category',
  usable_recall: 'Usable',
}
