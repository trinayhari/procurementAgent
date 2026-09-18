import { useCallback, useEffect, useMemo, useState } from 'react'
import ComparePanel from './ComparePanel'
import CorpusPanel from './CorpusPanel'
import ResultsPanel from './ResultsPanel'
import RunPanel from './RunPanel'
import RunsPanel from './RunsPanel'
import { API_BASE, MOCK, cancelRun, compareRuns, createRuns, deleteRun, getCorpus, getPlanTypes, getRun, getStatus, listRuns, getVariants } from './api'
import { Box, badge, css, num } from './lib'
import type { CompareOut, CorpusOut, PlanTypeOut, RunDetailOut, RunSummaryOut, StatusOut, VariantOut } from './types'

// Proq extraction bench. Four panels: pick documents, describe a run, read the
// per-document diff, compare two runs. Loading data is automatic; starting a run
// never is — see docs/eval-harness.md §6.

const POLL_MS = 2000

function msg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

export default function App() {
  const [status, setStatus] = useState<StatusOut | null>(null)
  const [corpus, setCorpus] = useState<CorpusOut | null>(null)
  const [planTypes, setPlanTypes] = useState<PlanTypeOut[]>([])
  const [variants, setVariants] = useState<VariantOut[]>([])
  const [runs, setRuns] = useState<RunSummaryOut[]>([])
  const [detail, setDetail] = useState<RunDetailOut | null>(null)

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [planType, setPlanType] = useState('')
  const [variantIds, setVariantIds] = useState<string[]>(['baseline'])
  const [trials, setTrials] = useState(1) // never higher by default: every trial is a paid call
  const [notes, setNotes] = useState('')

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [compareA, setCompareA] = useState<string | null>(null)
  const [compareB, setCompareB] = useState<string | null>(null)
  const [comparison, setComparison] = useState<CompareOut | null>(null)
  const [tab, setTab] = useState<'results' | 'compare'>('results')

  const [loading, setLoading] = useState(true)
  const [runsLoading, setRunsLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [compareLoading, setCompareLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string | null>>({})
  const setError = (k: string, v: string | null) => setErrors((e) => ({ ...e, [k]: v }))

  const docs = useMemo(
    () => new Map((corpus?.documents || []).map((d) => [d.id, d])),
    [corpus],
  )

  const refreshRuns = useCallback(async () => {
    try {
      setRuns(await listRuns(50))
      setError('runs', null)
    } catch (e) {
      setError('runs', msg(e))
    } finally {
      setRunsLoading(false)
    }
  }, [])

  const refreshDetail = useCallback(async (id: string) => {
    try {
      setDetail(await getRun(id))
      setError('detail', null)
    } catch (e) {
      setError('detail', msg(e))
    } finally {
      setDetailLoading(false)
    }
  }, [])

  // Initial load. Reading the corpus and the run history is free; nothing here
  // starts an extraction.
  useEffect(() => {
    let live = true
    ;(async () => {
      const settle = async <T,>(key: string, p: Promise<T>, set: (v: T) => void) => {
        try {
          const v = await p
          if (live) { set(v); setError(key, null) }
        } catch (e) {
          if (live) setError(key, msg(e))
        }
      }
      await Promise.all([
        settle('status', getStatus(), setStatus),
        settle('corpus', getCorpus(), setCorpus),
        settle('planTypes', getPlanTypes(), setPlanTypes),
        settle('variants', getVariants(), setVariants),
        refreshRuns(),
      ])
      if (live) setLoading(false)
    })()
    return () => { live = false }
  }, [refreshRuns])

  useEffect(() => {
    if (!selectedRunId) { setDetail(null); return }
    setDetailLoading(true)
    refreshDetail(selectedRunId)
  }, [selectedRunId, refreshDetail])

  // Poll while anything is in flight — a run is minutes long and the contract is
  // explicit that there is no SSE.
  const active = runs.some((r) => r.status === 'running' || r.status === 'queued')
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => {
      refreshRuns()
      if (selectedRunId) refreshDetail(selectedRunId)
    }, POLL_MS)
    return () => clearInterval(t)
  }, [active, selectedRunId, refreshRuns, refreshDetail])

  useEffect(() => {
    if (!compareA || !compareB || compareA === compareB) { setComparison(null); return }
    let live = true
    setCompareLoading(true)
    compareRuns(compareA, compareB).then(
      (c) => { if (live) { setComparison(c); setError('compare', null) } },
      (e) => { if (live) { setComparison(null); setError('compare', msg(e)) } },
    ).finally(() => { if (live) setCompareLoading(false) })
    return () => { live = false }
  }, [compareA, compareB])

  const onRun = async () => {
    setStarting(true)
    setError('start', null)
    try {
      const { run_ids } = await createRuns({
        doc_ids: [...selected],
        variant_ids: variantIds,
        plan_type: planType || null,
        trials,
        notes: notes || null,
      })
      await refreshRuns()
      if (run_ids[0]) { setSelectedRunId(run_ids[0]); setTab('results') }
      // Two variants in one press is a comparison waiting to happen — pin it.
      if (run_ids.length >= 2) { setCompareA(run_ids[0]); setCompareB(run_ids[1]) }
    } catch (e) {
      setError('start', msg(e))
    } finally {
      setStarting(false)
    }
  }

  const onCancel = async (id: string) => {
    try {
      await cancelRun(id)
      await refreshRuns()
      if (selectedRunId) refreshDetail(selectedRunId)
    } catch (e) {
      setError('detail', msg(e))
    }
  }

  const onDelete = async (id: string) => {
    try {
      await deleteRun(id)
      if (selectedRunId === id) { setSelectedRunId(null); setDetail(null) }
      if (compareA === id) setCompareA(null)
      if (compareB === id) setCompareB(null)
      await refreshRuns()
    } catch (e) {
      setError('detail', msg(e))
    }
  }

  const onPin = (slot: 'a' | 'b', id: string) => {
    if (slot === 'a') setCompareA((c) => (c === id ? null : id))
    else setCompareB((c) => (c === id ? null : id))
    setTab('compare')
  }

  const tabCss = (on: boolean) =>
    `height:26px;padding:0 12px;border-radius:7px;font-size:12.5px;font-weight:600;border:1px solid ${on ? 'var(--primary)' : 'var(--border-strong)'};background:${on ? 'var(--primary)' : 'var(--panel)'};color:${on ? 'var(--on-primary)' : 'var(--text-2)'}`

  return (
    <div style={css('height:100vh;display:flex;flex-direction:column;overflow:hidden')}>
      {/* The fixture adapter is fake data end to end; say so permanently and
          loudly, or the no-placeholder-data rule is broken by this very tool. */}
      {MOCK ? (
        <div style={css('background:#7c3aed;color:#fff;padding:6px 14px;font-size:12.5px;font-weight:600;letter-spacing:.01em')}>
          MOCK ADAPTER — the bench API is not being called. Every document, run and number on this screen is a fixture
          from <code style={css('font-family:var(--mono)')}>src/mock.ts</code>, not a measurement. Reload without{' '}
          <code style={css('font-family:var(--mono)')}>?mock=1</code> / <code style={css('font-family:var(--mono)')}>VITE_BENCH_MOCK=1</code> to talk to {API_BASE}.
        </div>
      ) : null}

      <header style={css('display:flex;align-items:center;gap:12px;padding:8px 14px;background:var(--panel);border-bottom:1px solid var(--border);flex:none')}>
        <span style={css('font-size:14px;font-weight:800;letter-spacing:-.01em')}>Proq bench</span>
        <span style={css('font-size:11.5px;color:var(--text-3)')}>extraction accuracy · BOM only</span>
        <span style={css('flex:1')} />
        {status ? (
          <>
            <span style={css('font-family:var(--mono);font-size:11px;color:var(--text-3)')} title={status.corpus_dir}>
              {status.corpus_dir}
            </span>
            <span style={badge('gray')}>{num(status.docs)} docs · {num(status.labelled)} labelled</span>
            <span style={badge(status.live_extraction ? 'success' : 'danger')}>
              {status.live_extraction ? 'live extraction' : 'NO API KEY — runs would be mocked'}
            </span>
          </>
        ) : (
          <span style={badge(errors.status ? 'danger' : 'gray')}>
            {errors.status ? `API unreachable at ${API_BASE}` : 'connecting…'}
          </span>
        )}
      </header>

      {errors.status && !MOCK ? (
        <div style={css('background:var(--danger-soft);color:var(--danger);padding:7px 14px;font-size:12px;flex:none')}>
          {errors.status} — start the bench API with the <code>bench-api</code> launch config (port 8040), or set{' '}
          <code>VITE_BENCH_API_URL</code> if it runs elsewhere.
        </div>
      ) : null}

      <div style={css('flex:none;display:flex;gap:10px;padding:10px 10px 0;height:326px;min-height:0')}>
        <CorpusPanel
          corpus={corpus}
          planTypes={planTypes}
          selected={selected}
          onChange={setSelected}
          loading={loading}
          error={errors.corpus || null}
        />
        <RunPanel
          status={status}
          planTypes={planTypes}
          variants={variants}
          docs={docs}
          selectedDocs={[...selected]}
          planType={planType}
          onPlanType={setPlanType}
          variantIds={variantIds}
          onVariantIds={setVariantIds}
          trials={trials}
          onTrials={setTrials}
          notes={notes}
          onNotes={setNotes}
          onRun={onRun}
          starting={starting}
          error={errors.start || null}
        />
        <RunsPanel
          runs={runs}
          selectedId={selectedRunId}
          onSelect={(id) => { setSelectedRunId(id); setTab('results') }}
          compareA={compareA}
          compareB={compareB}
          onPin={onPin}
          loading={runsLoading}
          error={errors.runs || null}
          onRefresh={refreshRuns}
        />
      </div>

      <div style={css('display:flex;align-items:center;gap:8px;padding:10px 12px 6px;flex:none')}>
        <Box as="button" type="button" onClick={() => setTab('results')} css={tabCss(tab === 'results')}>Results</Box>
        <Box as="button" type="button" onClick={() => setTab('compare')} css={tabCss(tab === 'compare')}>
          Compare{compareA && compareB ? ' · A/B pinned' : ''}
        </Box>
        {errors.detail ? <span style={css('font-size:11.5px;color:var(--danger)')}>{errors.detail}</span> : null}
      </div>

      <div style={css('flex:1;min-height:0;display:flex;padding:0 10px 10px')}>
        {tab === 'results' ? (
          <ResultsPanel
            run={detail}
            docs={docs}
            loading={detailLoading}
            onCancel={onCancel}
            onDelete={onDelete}
          />
        ) : (
          <ComparePanel
            data={comparison}
            loading={compareLoading}
            error={errors.compare || null}
            aId={compareA}
            bId={compareB}
          />
        )}
      </div>
    </div>
  )
}
