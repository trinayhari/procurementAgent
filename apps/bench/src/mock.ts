// ============================================================================
// DEV-ONLY FIXTURE ADAPTER — NOT REAL DATA. NOT REACHABLE IN A NORMAL RUN.
// ============================================================================
// Track C (this app) is built against the frozen HTTP contract while Track B
// builds the API, so `/bench/*` does not exist yet. This module answers the
// same routes with fixtures shaped exactly like docs/eval-harness.md §3, so the
// UI can be developed and verified end to end.
//
// It is reached only through the single `MOCK` switch in api.ts
// (`import.meta.env.DEV && (VITE_BENCH_MOCK=1 || ?mock=1)`), and the whole
// module is dropped from a production build. When it IS active the app shows a
// permanent banner saying so — none of the numbers below are measurements, and
// the no-placeholder-data rule means the user must never mistake them for one.
//
// The scores here are computed from the fixture match lists by the same
// definitions the real scorer uses (recall = hits / required truth items,
// precision only on `full` truth), so the UI is exercised against internally
// consistent numbers rather than hand-typed ones.
import type {
  CompareOut, CorpusDocOut, CorpusOut, CreateRunBody, CreateRunOut, DocScoreOut,
  ExtractedGroup, ItemMatchOut, PlanTypeOut, RunDetailOut, RunMetrics, RunSummary,
  RunSummaryOut, StatusOut, TrialOut, VariantOut,
} from './types'

// ------------------------------------------------------------------- corpus

const CORPUS: CorpusDocOut[] = [
  {
    id: 'site-nc-greenway-01', title: 'Greenway Utilities Extension — Civil Set', plan_type: 'site_plan',
    path: '/bench-corpus/docs/site-nc-greenway-01.pdf', exists: true,
    source_url: 'https://example.gov/plans/greenway.pdf', source_name: 'City of Example, NC — Public Works',
    license: 'public-domain-usgov', retrieved_at: '2026-08-04', sha256: 'a91f…', bytes: 8123456,
    pages: 34, has_text_layer: true, tags: ['utilities', 'municipal', 'vector-cad'], has_truth: true,
  },
  {
    id: 'site-tx-frontage-02', title: 'FM 1960 Frontage Widening — Paving & Drainage', plan_type: 'site_plan',
    path: '/bench-corpus/docs/site-tx-frontage-02.pdf', exists: true,
    source_url: 'https://example.tx.gov/fm1960.pdf', source_name: 'TxDOT District 12',
    license: 'public-domain-usgov', retrieved_at: '2026-08-05', sha256: '4c02…', bytes: 22456789,
    pages: 88, has_text_layer: true, tags: ['paving', 'drainage', 'dense'], has_truth: true,
  },
  {
    id: 'bldg-mn-clinic-03', title: 'Lakeside Clinic — Architectural Set', plan_type: 'building_plan',
    path: '/bench-corpus/docs/bldg-mn-clinic-03.pdf', exists: true,
    source_url: null, source_name: 'Anonymised GC submission',
    license: 'local-only', retrieved_at: '2026-07-29', sha256: 'de71…', bytes: 15903211,
    pages: 52, has_text_layer: true, tags: ['healthcare', 'interior'], has_truth: true,
  },
  {
    id: 'elec-ca-substation-04', title: 'Ridgecrest Substation — Electrical', plan_type: 'electrical_plan',
    path: '/bench-corpus/docs/elec-ca-substation-04.pdf', exists: true,
    source_url: 'https://example.ca.gov/ridgecrest.pdf', source_name: 'Ridgecrest Municipal Utility',
    license: 'public-domain', retrieved_at: '2026-08-01', sha256: '77bd…', bytes: 6104332,
    pages: 27, has_text_layer: false, tags: ['scanned', 'switchgear'], has_truth: true,
  },
  {
    id: 'bldg-or-annex-12', title: 'County Annex Remodel — Full Set', plan_type: 'building_plan',
    path: '/bench-corpus/docs/bldg-or-annex-12.pdf', exists: true,
    source_url: 'https://example.or.gov/annex.pdf', source_name: 'Example County, OR',
    license: 'public-domain-usgov', retrieved_at: '2026-08-08', sha256: '1ee4…', bytes: 41220110,
    pages: 140, has_text_layer: true, tags: ['remodel', 'large'], has_truth: false,
  },
  {
    id: 'site-wa-culvert-07', title: 'Culvert Replacement — SR 902', plan_type: 'site_plan',
    path: '/bench-corpus/docs/site-wa-culvert-07.pdf', exists: false,
    source_url: 'https://example.wa.gov/sr902.pdf', source_name: 'WSDOT',
    license: 'local-only', retrieved_at: '2026-08-09', sha256: 'b3aa…', bytes: 3391220,
    pages: 12, has_text_layer: true, tags: ['culvert'], has_truth: true,
  },
]

const PROBLEMS = [
  'site-wa-culvert-07: PDF not present locally (license "local-only" — run scripts/fetch_corpus.py to retrieve it).',
]

// The registered plan types and their category keys, per extraction.registry.
const PLAN_TYPES: PlanTypeOut[] = [
  {
    key: 'site_plan', label: 'Site / Civil', description: 'Utilities, grading, erosion control.', enabled: true,
    categories: [
      { key: 'water', label: 'Water', tone: 'blue' },
      { key: 'sewer', label: 'Sanitary sewer', tone: 'violet' },
      { key: 'storm', label: 'Storm drainage', tone: 'gray' },
      { key: 'erosion', label: 'Erosion control', tone: 'warn' },
    ],
  },
  {
    key: 'building_plan', label: 'Building', description: 'Structure, envelope, framing.', enabled: true,
    categories: [
      { key: 'concrete', label: 'Concrete', tone: 'gray' },
      { key: 'rebar', label: 'Rebar', tone: 'warn' },
      { key: 'steel', label: 'Structural steel', tone: 'blue' },
      { key: 'masonry', label: 'Masonry', tone: 'violet' },
      { key: 'framing', label: 'Framing', tone: 'gray' },
    ],
  },
  {
    key: 'electrical_plan', label: 'Electrical', description: 'Raceway, conductors, equipment, devices.', enabled: true,
    categories: [
      { key: 'raceway', label: 'Raceway', tone: 'blue' },
      { key: 'conductors', label: 'Conductors', tone: 'violet' },
      { key: 'equipment', label: 'Equipment', tone: 'warn' },
      { key: 'devices', label: 'Devices', tone: 'gray' },
      { key: 'lighting', label: 'Lighting', tone: 'blue' },
      { key: 'grounding', label: 'Grounding', tone: 'gray' },
      { key: 'lowvoltage', label: 'Low voltage', tone: 'violet' },
    ],
  },
  { key: 'other', label: 'Other', description: 'No category structure.', enabled: true, categories: [] },
]

const VARIANTS: VariantOut[] = [
  {
    id: 'baseline', label: 'Baseline', description: 'The live configuration, unmodified.',
    settings: {}, prompts: {}, spec_overrides: {},
  },
  {
    id: 'text-first-strict', label: 'Text-first, stricter escalation',
    description: 'Raise the text-pass floor so thin text results escalate to vision.',
    settings: { text_pass_min_items: 8, vision_tile_cols: 4 },
    prompts: { SYSTEM_PROMPT: '…' },
    spec_overrides: { site_plan: { prefer_vision: false } },
  },
  {
    id: 'vision-dense', label: 'Dense vision tiles',
    description: 'Finer tile grid on every sheet — slower, better on symbol counts.',
    settings: { vision_tile_cols: 5, vision_dense_tile_cols: 6 },
    prompts: {},
    spec_overrides: {},
  },
]

// ------------------------------------------------- fixture matches per doc

// Fixture-authoring shape: truth side and extraction side written out
// separately, then folded into the wire's got/want pairs by fill().
type M = {
  kind: ItemMatchOut['kind']
  score?: number
  category_ok?: boolean
  quantity_ok?: boolean
  unit_ok?: boolean
  truth_name?: string
  truth_category?: string
  truth_quantity?: number | null
  truth_unit?: string | null
  truth_required?: boolean
  truth_source?: string
  extracted_name?: string
  extracted_category?: string | null
  extracted_quantity?: number | null
  extracted_unit?: string | null
  forbidden_why?: string
}

// Baseline match lists. Each entry is one truth item, one extracted item, or a
// pairing of the two — exactly what scoring.ItemMatch describes. Categories are
// the registered keys for each plan type.
const MATCHES: Record<string, M[]> = {
  'site-nc-greenway-01': [
    { kind: 'hit', truth_name: '12" DI Pipe, Class 350', truth_category: 'water', truth_quantity: 1450, truth_unit: 'LF', extracted_name: '12 inch ductile iron pipe (CL 350)', extracted_category: 'water', extracted_quantity: 1450, extracted_unit: 'LF', score: 0.94 },
    { kind: 'hit', truth_name: '8" PVC C900 Waterline', truth_category: 'water', truth_quantity: 890, truth_unit: 'LF', extracted_name: '8" PVC waterline (C900)', extracted_category: 'water', extracted_quantity: 640, extracted_unit: 'LF', score: 0.91, quantity_ok: false, truth_source: 'Sheet C-4, utility summary' },
    { kind: 'hit', truth_name: 'Ductile Iron Fittings', truth_category: 'water', truth_quantity: 4800, truth_unit: 'LB', extracted_name: 'DI fittings', extracted_category: 'water', extracted_quantity: 4800, extracted_unit: 'EA', score: 0.87, unit_ok: false },
    { kind: 'hit', truth_name: '4" Gate Valve w/ Box', truth_category: 'water', truth_quantity: 8, truth_unit: 'EA', extracted_name: '4 inch gate valve with valve box', extracted_category: 'storm', extracted_quantity: 8, extracted_unit: 'EA', score: 0.9, category_ok: false },
    { kind: 'miss', truth_name: 'Fire Hydrant Assembly', truth_category: 'water', truth_quantity: 6, truth_unit: 'EA', truth_source: 'Sheet C-4, utility summary' },
    { kind: 'miss', truth_name: 'Concrete Thrust Block', truth_category: 'water', truth_quantity: 12, truth_unit: 'EA', truth_required: false, truth_source: 'Detail 3/C-9' },
    { kind: 'extra', extracted_name: 'Trench Safety System', extracted_category: 'water', extracted_quantity: 1450, extracted_unit: 'LF' },
    { kind: 'forbidden', extracted_name: 'Silt fence', extracted_category: 'erosion', extracted_quantity: 900, extracted_unit: 'LF', forbidden_why: 'legend symbol only — not installed on this set' },
  ],
  'site-tx-frontage-02': [
    { kind: 'hit', truth_name: '18" RCP Class III', truth_category: 'storm', truth_quantity: 2400, truth_unit: 'LF', extracted_name: '18 inch RCP (Class III)', extracted_category: 'storm', extracted_quantity: 2400, extracted_unit: 'LF', score: 1 },
    { kind: 'hit', truth_name: '24" RCP Class III', truth_category: 'storm', truth_quantity: 1320, truth_unit: 'LF', extracted_name: '24 inch RCP (Class III)', extracted_category: 'storm', extracted_quantity: 1180, extracted_unit: 'LF', score: 0.93, quantity_ok: false, truth_source: 'Drainage summary, sheet D-2' },
    { kind: 'miss', truth_name: 'Curb Inlet, 10 ft', truth_category: 'storm', truth_quantity: 14, truth_unit: 'EA', truth_source: 'Drainage area map D-1' },
    { kind: 'unknown', extracted_name: 'Rock Check Dam', extracted_category: 'erosion', extracted_quantity: 26, extracted_unit: 'EA' },
    { kind: 'unknown', extracted_name: 'Silt Fence', extracted_category: 'erosion', extracted_quantity: 21000, extracted_unit: 'LF' },
  ],
  'bldg-mn-clinic-03': [
    { kind: 'hit', truth_name: 'Metal Stud, 3-5/8" 20ga', truth_category: 'framing', truth_quantity: 12400, truth_unit: 'LF', extracted_name: '3-5/8 inch metal stud, 20 ga', extracted_category: 'framing', extracted_quantity: 12400, extracted_unit: 'LF', score: 0.96 },
    { kind: 'hit', truth_name: '#5 Rebar, Grade 60', truth_category: 'rebar', truth_quantity: 41000, truth_unit: 'LB', extracted_name: 'Rebar #5 (Gr 60)', extracted_category: 'rebar', extracted_quantity: 41000, extracted_unit: 'LB', score: 0.95 },
    { kind: 'hit', truth_name: 'W12x26 Steel Beam', truth_category: 'steel', truth_quantity: 46, truth_unit: 'EA', extracted_name: 'W12x26 beam', extracted_category: 'steel', extracted_quantity: 52, extracted_unit: 'EA', score: 0.84, quantity_ok: false, truth_source: 'Framing plan S-201' },
    { kind: 'miss', truth_name: 'CMU 8x8x16, Normal Weight', truth_category: 'masonry', truth_quantity: 640, truth_unit: 'SF', truth_source: 'Elevations A-201' },
    { kind: 'extra', extracted_name: 'Slab-on-grade, 4" 4000psi', extracted_category: 'concrete', extracted_quantity: null, extracted_unit: null },
  ],
  'elec-ca-substation-04': [
    { kind: 'hit', truth_name: '600V THHN #12 Copper', truth_category: 'conductors', truth_quantity: 18000, truth_unit: 'LF', extracted_name: 'THHN #12 CU, 600V', extracted_category: 'conductors', extracted_quantity: 18000, extracted_unit: 'FT', score: 0.9 },
    { kind: 'hit', truth_name: '2" EMT Conduit', truth_category: 'raceway', truth_quantity: 3400, truth_unit: 'LF', extracted_name: '2 inch EMT', extracted_category: 'raceway', extracted_quantity: 3400, extracted_unit: 'LF', score: 0.92 },
    { kind: 'miss', truth_name: '200A Panelboard, 42-circuit', truth_category: 'equipment', truth_quantity: 2, truth_unit: 'EA', truth_source: 'Panel schedule E-401' },
    { kind: 'miss', truth_name: '15kV Load Break Switch', truth_category: 'equipment', truth_quantity: 3, truth_unit: 'EA', truth_source: 'One-line E-101' },
    { kind: 'extra', extracted_name: 'Grounding Bushing', extracted_category: 'grounding', extracted_quantity: 120, extracted_unit: 'EA' },
    { kind: 'forbidden', extracted_name: 'Emergency generator, 500 kW', extracted_category: 'equipment', extracted_quantity: 1, extracted_unit: 'EA', forbidden_why: 'design alternate — shown hatched, not in base bid' },
  ],
  'site-wa-culvert-07': [
    { kind: 'hit', truth_name: '48" CMP Culvert', truth_category: 'storm', truth_quantity: 180, truth_unit: 'LF', extracted_name: '48 inch CMP', extracted_category: 'storm', extracted_quantity: 180, extracted_unit: 'LF', score: 0.93 },
    { kind: 'miss', truth_name: 'Riprap, Heavy Loose', truth_category: 'storm', truth_quantity: 210, truth_unit: 'CY', truth_source: 'Sheet 4' },
  ],
}

const COMPLETENESS: Record<string, 'full' | 'partial'> = {
  'site-nc-greenway-01': 'full',
  'site-tx-frontage-02': 'partial',
  'bldg-mn-clinic-03': 'full',
  'elec-ca-substation-04': 'full',
  'site-wa-culvert-07': 'full',
}

// Variant effects, so a compare shows real movement rather than noise.
function applyVariant(rows: M[], variantId: string): M[] {
  if (variantId === 'text-first-strict') {
    const out = rows.slice()
    const i = out.findIndex((r) => r.kind === 'miss' && r.truth_required !== false)
    if (i >= 0) {
      const m = out[i]
      out[i] = {
        ...m, kind: 'hit', score: 0.88,
        extracted_name: m.truth_name, extracted_category: m.truth_category,
        extracted_quantity: m.truth_quantity, extracted_unit: m.truth_unit,
      }
    }
    // Stricter escalation reads more of the sheet, which also pulls in noise.
    out.push({ kind: 'extra', extracted_name: 'Misc. hardware allowance', extracted_category: rows[0]?.truth_category ?? null, extracted_quantity: null, extracted_unit: null })
    return out
  }
  if (variantId === 'vision-dense') {
    return rows.map((r) =>
      r.kind === 'hit' && r.quantity_ok === false
        ? { ...r, quantity_ok: undefined, extracted_quantity: r.truth_quantity }
        : r,
    )
  }
  return rows
}

// --------------------------------------------------------------- scoring

function fill(m: M, ti: number, ei: number): ItemMatchOut {
  const paired = m.kind === 'hit'
  return {
    truth_index: m.truth_name ? ti : null,
    extracted_index: m.extracted_name ? ei : null,
    score: m.score ?? (paired ? 0.9 : 0),
    category_ok: m.category_ok ?? true,
    quantity_ok: paired ? (m.quantity_ok ?? (m.truth_quantity === null || m.truth_quantity === undefined ? null : true)) : null,
    unit_ok: paired ? (m.unit_ok ?? (m.truth_unit ? true : null)) : null,
    kind: m.kind,
    truth_name: m.truth_name ?? null,
    extracted_name: m.extracted_name ?? null,
    quantity_got: m.extracted_quantity ?? null,
    quantity_want: m.truth_quantity ?? null,
    unit_got: m.extracted_unit ?? null,
    unit_want: m.truth_unit ?? null,
    required: m.truth_required ?? (m.truth_name ? true : null),
    truth_category: m.truth_category ?? null,
    extracted_category: m.extracted_category ?? null,
    truth_source: m.truth_source ?? null,
    qty_tolerance: m.truth_name ? 0.05 : null,
    extracted_display: null,
    forbidden_why: m.forbidden_why ?? null,
  }
}

function scoreDoc(docId: string, planType: string, variantId: string): DocScoreOut | null {
  const rows = MATCHES[docId]
  if (!rows) return null
  const completeness = COMPLETENESS[docId] || 'full'
  let ti = 0
  let ei = 0
  const matches = applyVariant(rows, variantId).map((m) => fill(m, m.truth_name ? ti++ : -1, m.extracted_name ? ei++ : -1))

  const counts = {
    hit: matches.filter((m) => m.kind === 'hit').length,
    miss: matches.filter((m) => m.kind === 'miss').length,
    extra: matches.filter((m) => m.kind === 'extra').length,
    unknown: matches.filter((m) => m.kind === 'unknown').length,
    forbidden: matches.filter((m) => m.kind === 'forbidden').length,
    truth_total: matches.filter((m) => m.truth_name).length,
    extracted_total: matches.filter((m) => m.extracted_name).length,
  }

  const requiredHits = matches.filter((m) => m.kind === 'hit' && m.required !== false).length
  const requiredTruth = matches.filter((m) => m.truth_name && m.required !== false).length
  const optionalTruth = matches.filter((m) => m.truth_name && m.required === false).length
  const optionalHits = matches.filter((m) => m.kind === 'hit' && m.required === false).length

  const recall = requiredTruth ? requiredHits / requiredTruth : null
  // Precision is only meaningful on `full` truth: on a partial doc an unmatched
  // extraction is `unknown`, not a false positive (eval-harness.md §1).
  const precision = completeness !== 'full'
    ? null
    : counts.hit + counts.extra > 0 ? counts.hit / (counts.hit + counts.extra) : null
  const f1 = recall !== null && precision !== null && recall + precision > 0
    ? (2 * recall * precision) / (recall + precision)
    : null

  const qtyJudged = matches.filter((m) => m.kind === 'hit' && m.quantity_ok !== null)
  const unitJudged = matches.filter((m) => m.kind === 'hit' && m.unit_ok !== null)
  const hits = matches.filter((m) => m.kind === 'hit')

  return {
    doc_id: docId,
    plan_type: planType,
    precision,
    recall,
    f1,
    optional_recall: optionalTruth ? optionalHits / optionalTruth : null,
    quantity_accuracy: qtyJudged.length ? qtyJudged.filter((m) => m.quantity_ok).length / qtyJudged.length : null,
    unit_accuracy: unitJudged.length ? unitJudged.filter((m) => m.unit_ok).length / unitJudged.length : null,
    category_accuracy: hits.length ? hits.filter((m) => m.category_ok).length / hits.length : null,
    usable_recall: requiredTruth
      ? hits.filter((m) => m.required && m.quantity_ok !== false && m.unit_ok !== false).length / requiredTruth
      : null,
    hallucinations: counts.forbidden,
    counts,
    matches,
    completeness,
  }
}

function groupsFor(score: DocScoreOut | null, docId: string): ExtractedGroup[] {
  const rows = score
    ? score.matches.filter((m) => m.extracted_name)
    : []
  const byCat = new Map<string, { n: string; q: string }[]>()
  for (const m of rows) {
    const key = m.extracted_category || 'uncategorised'
    const q = m.quantity_got === null || m.quantity_got === undefined
      ? '—'
      : `${m.quantity_got.toLocaleString()}${m.unit_got ? ` ${m.unit_got}` : ''}`
    if (!byCat.has(key)) byCat.set(key, [])
    byCat.get(key)!.push({ n: m.extracted_name!, q })
  }
  if (!byCat.size) return [] // unlabelled doc: the fixture has no items to show
  return [...byCat.entries()].map(([group, items]) => ({ group, count: items.length, items }))
}

function aggregate(scores: DocScoreOut[], mockedTrials: number, unlabelled: number): RunSummary {
  const avg = (pick: (s: DocScoreOut) => number | null): number | null => {
    const vals = scores.map(pick).filter((v): v is number => v !== null && v !== undefined)
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null
  }
  const metrics: RunMetrics = {
    documents: scores.length,
    precision: avg((s) => s.precision),
    recall: avg((s) => s.recall),
    f1: avg((s) => s.f1),
    optional_recall: avg((s) => s.optional_recall),
    quantity_accuracy: avg((s) => s.quantity_accuracy),
    unit_accuracy: avg((s) => s.unit_accuracy),
    category_accuracy: avg((s) => s.category_accuracy),
    usable_recall: avg((s) => s.usable_recall),
    hallucinations: scores.reduce((a, s) => a + s.hallucinations, 0),
  }
  // Mirrors the real runner: live metrics and mocked metrics never share a field.
  const allMocked = mockedTrials > 0 && scores.length === 0
  return {
    variant_id: '',
    trials_total: scores.length + mockedTrials + unlabelled,
    trials_run: scores.length + mockedTrials + unlabelled,
    trials_ok: scores.length + mockedTrials,
    trials_failed: 0,
    trials_mocked: mockedTrials,
    trials_unlabelled: unlabelled,
    trials_scored: scores.length,
    mocked: mockedTrials > 0,
    latency_ms_avg: null,
    metrics: allMocked ? null : metrics,
    mocked_metrics: allMocked ? metrics : null,
    note: allMocked ? 'no live, labelled trials — nothing to average' : null,
  }
}

// ----------------------------------------------------------------- run store

type MockRun = RunSummaryOut & { trials_detail: TrialOut[]; _startedAt?: number; _mocked?: boolean }

const runs = new Map<string, MockRun>()
let seq = 0

function isoAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60000).toISOString()
}

function buildTrials(run: MockRun, upTo: number): TrialOut[] {
  const out: TrialOut[] = []
  let i = 0
  for (const docId of run.doc_ids) {
    for (let t = 0; t < run.trials; t++) {
      if (i >= upTo) return out
      const doc = CORPUS.find((d) => d.id === docId)
      const planType = run.plan_type || doc?.plan_type || 'site'
      // A mocked extraction is still scored by the runner — that is exactly why
      // the flag has to travel with the trial and be loud in the UI.
      const score = scoreDoc(docId, planType, run.variant_id)
      out.push({
        id: `${run.id}-t${i}`,
        run_id: run.id,
        doc_id: docId,
        variant_id: run.variant_id,
        trial_index: t,
        status: 'done',
        started_at: run.created_at,
        finished_at: run.created_at,
        latency_ms: 42000 + ((docId.length * 7919 + t * 1301 + run.variant_id.length * 331) % 90000),
        error: null,
        groups: groupsFor(score, docId),
        summary_text: null,
        mocked: !!run._mocked,
        score,
      })
      i++
    }
  }
  return out
}

function finalize(run: MockRun): void {
  run.trials_detail = buildTrials(run, run.progress_total)
  const scores = run.trials_detail.map((t) => t.score).filter((s): s is DocScoreOut => !!s)
  const unlabelled = run.trials_detail.filter((t) => !t.score && !t.error).length
  run.progress_done = run.progress_total
  run.status = 'done'
  run.finished_at = new Date().toISOString()
  const mockedTrials = run.trials_detail.filter((t) => t.mocked).length
  run.summary = aggregate(scores, mockedTrials, unlabelled)
  run.summary.variant_id = run.variant_id
  run.mocked_trials = mockedTrials  // row-level, so the runs list can badge it
}

function tick(run: MockRun): void {
  if (run.status !== 'running' || !run._startedAt) return
  const done = Math.min(run.progress_total, Math.floor((Date.now() - run._startedAt) / 1400))
  run.progress_done = done
  run.trials_detail = buildTrials(run, done)
  if (done >= run.progress_total) finalize(run)
}

function seed(): void {
  if (runs.size) return
  const docs = ['site-nc-greenway-01', 'site-tx-frontage-02', 'bldg-mn-clinic-03', 'elec-ca-substation-04']
  const make = (variant: string, minutesAgo: number, notes: string, mocked = false): MockRun => {
    const run: MockRun = {
      id: `fixture-${variant}${mocked ? '-mocked' : ''}`,
      created_at: isoAgo(minutesAgo),
      finished_at: isoAgo(minutesAgo - 6),
      status: 'done',
      variant_id: variant,
      plan_type: null,
      doc_ids: docs,
      trials: 1,
      notes,
      progress_done: docs.length,
      progress_total: docs.length,
      error: null,
      summary: null,
      mocked_trials: null,
      trials_detail: [],
      _mocked: mocked,
    }
    finalize(run)
    run.finished_at = isoAgo(minutesAgo - 6)
    return run
  }
  for (const r of [
    make('baseline', 190, 'prompt-v3 A/B'),
    make('text-first-strict', 176, 'prompt-v3 A/B'),
    make('baseline', 640, 'no API key on this machine', true),
  ]) runs.set(r.id, r)
}

// -------------------------------------------------------------- the adapter

const STATUS: StatusOut = {
  enabled: true,
  corpus_dir: '/Users/you/procurementAgent/bench-corpus',
  docs: CORPUS.length,
  labelled: CORPUS.filter((d) => d.has_truth).length,
  live_extraction: true,
}

export async function mockRequest<T>(path: string, init?: RequestInit): Promise<T> {
  seed()
  await new Promise((r) => setTimeout(r, 120)) // a plausible localhost round-trip
  const method = (init?.method || 'GET').toUpperCase()
  const [route, query] = path.split('?')
  const params = new URLSearchParams(query || '')

  if (route === '/bench/status') return STATUS as unknown as T
  if (route === '/bench/corpus') return { documents: CORPUS, problems: PROBLEMS } as CorpusOut as unknown as T
  if (route === '/bench/plan-types') return PLAN_TYPES as unknown as T
  if (route === '/bench/variants') return VARIANTS as unknown as T

  if (route === '/bench/runs' && method === 'POST') {
    const body = JSON.parse(String(init?.body || '{}')) as CreateRunBody
    const ids: string[] = []
    for (const variantId of body.variant_ids) {
      const id = `mock-${Date.now().toString(36)}-${seq++}`
      const run: MockRun = {
        id,
        created_at: new Date().toISOString(),
        finished_at: null,
        status: 'running',
        variant_id: variantId,
        plan_type: body.plan_type ?? null,
        doc_ids: body.doc_ids,
        trials: body.trials,
        notes: body.notes ?? null,
        progress_done: 0,
        progress_total: body.doc_ids.length * body.trials,
        error: null,
        summary: null,
        mocked_trials: null,
        trials_detail: [],
        _startedAt: Date.now(),
      }
      runs.set(id, run)
      ids.push(id)
    }
    return { run_ids: ids } as CreateRunOut as unknown as T
  }

  if (route === '/bench/runs/compare') {
    const a = runs.get(params.get('a') || '')
    const b = runs.get(params.get('b') || '')
    if (!a || !b) throw new Error('Run not found')
    tick(a); tick(b)
    const byDoc = (r: MockRun) => new Map(r.trials_detail.filter((t) => t.score).map((t) => [t.doc_id, t.score!]))
    const ma = byDoc(a)
    const mb = byDoc(b)
    const docIds = [...new Set([...a.doc_ids, ...b.doc_ids])]
    const d = (k: keyof RunMetrics): number | null => {
      const av = a.summary?.metrics?.[k]
      const bv = b.summary?.metrics?.[k]
      return typeof av === 'number' && typeof bv === 'number' ? bv - av : null
    }
    return {
      a: strip(a),
      b: strip(b),
      deltas: {
        precision: d('precision'), recall: d('recall'), f1: d('f1'),
        optional_recall: d('optional_recall'), quantity_accuracy: d('quantity_accuracy'),
        unit_accuracy: d('unit_accuracy'), category_accuracy: d('category_accuracy'),
        usable_recall: d('usable_recall'),
        hallucinations: d('hallucinations'),
      },
      per_doc: docIds.map((doc_id) => ({ doc_id, a: ma.get(doc_id) || null, b: mb.get(doc_id) || null })),
    } as CompareOut as unknown as T
  }

  if (route === '/bench/runs' && method === 'GET') {
    const limit = Number(params.get('limit') || 50)
    const all = [...runs.values()]
    all.forEach(tick)
    all.sort((x, y) => (x.created_at < y.created_at ? 1 : -1))
    return all.slice(0, limit).map(strip) as unknown as T
  }

  const m = route.match(/^\/bench\/runs\/([^/]+)(\/cancel)?$/)
  if (m) {
    const run = runs.get(decodeURIComponent(m[1]))
    if (!run) throw new Error(`Run ${m[1]} not found`)
    if (m[2] === '/cancel') {
      if (run.status === 'running') {
        run.status = 'cancelled'
        run.finished_at = new Date().toISOString()
        return { cancelled: true } as unknown as T
      }
      return { cancelled: false } as unknown as T
    }
    if (method === 'DELETE') {
      runs.delete(run.id)
      return { deleted: true } as unknown as T
    }
    tick(run)
    return { ...strip(run), trials_detail: run.trials_detail } as RunDetailOut as unknown as T
  }

  throw new Error(`mock adapter: no fixture for ${method} ${path}`)
}

function strip(r: MockRun): RunSummaryOut {
  const { trials_detail, _startedAt, _mocked, ...rest } = r
  return rest
}
