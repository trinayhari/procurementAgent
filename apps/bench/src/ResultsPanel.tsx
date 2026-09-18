import { useMemo, useState } from 'react'
import DocDiff from './DocDiff'
import { Box, Btn, Empty, Panel, badge, css, metric, ms, num, runMetrics } from './lib'
import { METRIC_LABELS } from './types'
import type { CorpusDocOut, MetricKey, RunDetailOut, TrialOut } from './types'

// Headline metrics for one run, then the per-document rows that expand into the
// diff. Everything here is read-only: nothing on this panel starts a run.

const HEADLINE: MetricKey[] = ['precision', 'recall', 'f1', 'quantity_accuracy', 'unit_accuracy', 'category_accuracy']

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div style={css('flex:1;min-width:92px')} title={hint}>
      <div style={css('font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)')}>{label}</div>
      <div style={css(`font-family:var(--mono);font-size:21px;font-weight:600;line-height:1.25;color:${value === '—' ? 'var(--text-3)' : 'var(--text)'}`)}>
        {value}
      </div>
    </div>
  )
}

// Per-document counts, in the order they matter when you are fixing something.
function Counts({ trial }: { trial: TrialOut }) {
  const s = trial.score
  if (!s) return <span style={badge('gray')}>no truth</span>
  const c = s.counts
  const wrongQty = s.matches.filter((m) => m.kind === 'hit' && m.quantity_ok === false).length
  const cells: [string, number, string][] = [
    ['✗', c.miss, 'danger'],
    ['≠', wrongQty, 'warn'],
    ['!', c.forbidden, 'danger'],
    ['+', c.extra, 'warn'],
    ['?', c.unknown, 'gray'],
    ['✓', c.hit, 'success'],
  ]
  return (
    <span style={css('display:inline-flex;gap:4px')}>
      {cells.map(([g, n, t]) => (
        <span key={g} style={badge(n ? t : 'gray', { opacity: n ? 1 : 0.4, minWidth: 34, justifyContent: 'center' })}>
          {g} {n}
        </span>
      ))}
    </span>
  )
}

export default function ResultsPanel({
  run, docs, loading, onCancel, onDelete,
}: {
  run: RunDetailOut | null
  docs: Map<string, CorpusDocOut>
  loading: boolean
  onCancel: (id: string) => void
  onDelete: (id: string) => void
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [problemsOnly, setProblemsOnly] = useState(false)

  const trials = run?.trials_detail || []
  const mockedTrials = trials.filter((t) => t.mocked).length

  // Worst first: the document with the most to fix is the one you came for.
  const ordered = useMemo(() => {
    const weight = (t: TrialOut) => {
      if (t.error) return 1e6
      const s = t.score
      if (!s) return -1
      const wrongQty = s.matches.filter((m) => m.kind === 'hit' && m.quantity_ok === false).length
      return s.counts.forbidden * 100 + s.counts.miss * 10 + wrongQty * 5 + s.counts.extra
    }
    return trials.slice().sort((a, b) => weight(b) - weight(a))
  }, [trials])

  const shown = problemsOnly
    ? ordered.filter((t) => t.error || (t.score && (t.score.counts.miss || t.score.counts.forbidden || t.score.counts.extra || t.score.matches.some((m) => m.kind === 'hit' && m.quantity_ok === false))))
    : ordered

  const running = run?.status === 'queued' || run?.status === 'running'
  // Live metrics only — `mocked_metrics` is deliberately never shown here.
  const headline = runMetrics(run)

  return (
    <Panel
      title="Results"
      subtitle={run ? `${run.variant_id} · ${run.doc_ids.length} doc${run.doc_ids.length === 1 ? '' : 's'} × ${run.trials} trial${run.trials === 1 ? '' : 's'}${run.notes ? ` · ${run.notes}` : ''}` : undefined}
      right={
        run ? (
          <span style={css('display:flex;align-items:center;gap:8px')}>
            <span style={badge(run.status === 'done' ? 'success' : run.status === 'failed' ? 'danger' : running ? 'blue' : 'gray')}>
              {run.status}
            </span>
            <span style={css('font-family:var(--mono);font-size:11px;color:var(--text-3)')}>{run.id}</span>
            {running ? <Btn kind="danger" onClick={() => onCancel(run.id)}>Cancel run</Btn> : null}
            {!running ? <Btn kind="danger" onClick={() => onDelete(run.id)}>Delete</Btn> : null}
          </span>
        ) : null
      }
      style="flex:1;min-height:0"
    >
      {!run ? (
        <Empty
          title={loading ? 'Loading run…' : 'No run selected'}
          hint="Pick a run from the list on the right, or select documents and start one. Nothing runs on its own — every run costs real model calls."
        />
      ) : (
        <div>
          {mockedTrials > 0 ? (
            <div style={css('background:var(--danger);color:#fff;padding:9px 12px;font-size:12.5px;font-weight:600;line-height:1.45')}>
              MOCKED — {mockedTrials} of {trials.length} extraction{trials.length === 1 ? '' : 's'} in this run came back
              from the mock pipeline (no OpenAI key at run time). These numbers are not accuracy results. Set
              <code style={css('font-family:var(--mono);margin:0 4px')}>PROCUREAI_OPENAI_API_KEY</code>
              and run again.
            </div>
          ) : null}

          {run.error ? (
            <div style={css('background:var(--danger-soft);color:var(--danger);padding:9px 12px;font-size:12.5px;border-bottom:1px solid var(--border)')}>
              <strong>Run failed.</strong> {run.error}
            </div>
          ) : null}

          {running ? (
            <div style={css('padding:9px 12px;border-bottom:1px solid var(--border);background:var(--primary-softer)')}>
              <div style={css('display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-2)')}>
                <span style={css('font-weight:600;color:var(--text)')}>
                  {run.progress_done} / {run.progress_total} extractions done
                </span>
                <span>· results appear as each document finishes</span>
              </div>
              <div style={css('height:5px;background:var(--panel-3);border-radius:99px;margin-top:6px;overflow:hidden')}>
                <div style={css(`height:100%;border-radius:99px;background:var(--primary);width:${run.progress_total ? (run.progress_done / run.progress_total) * 100 : 0}%`)} />
              </div>
            </div>
          ) : null}

          <div style={css('display:flex;gap:14px;padding:12px;border-bottom:1px solid var(--border);flex-wrap:wrap')}>
            {HEADLINE.map((k) => (
              <Metric
                key={k}
                label={METRIC_LABELS[k]}
                value={metric(headline ? headline[k] : null)}
                hint={k === 'precision' ? 'Macro-averaged over documents with full-completeness truth only.' : undefined}
              />
            ))}
            <div style={css('flex:1;min-width:92px')}>
              <div style={css('font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)')}>Hallucinations</div>
              <div style={css(`font-family:var(--mono);font-size:21px;font-weight:600;line-height:1.25;color:${headline?.hallucinations ? 'var(--danger)' : 'var(--text-3)'}`)}>
                {headline?.hallucinations === null || headline?.hallucinations === undefined ? '—' : num(headline.hallucinations)}
              </div>
            </div>
            <div style={css('flex:1;min-width:92px')}>
              <div style={css('font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)')}>Scored</div>
              <div style={css('font-family:var(--mono);font-size:21px;font-weight:600;line-height:1.25')}>
                {run.summary?.trials_scored === null || run.summary?.trials_scored === undefined ? '—' : num(run.summary.trials_scored)}
                <span style={css('font-size:12px;color:var(--text-3)')}> /{trials.length}</span>
              </div>
            </div>
          </div>

          {trials.length === 0 ? (
            <Empty
              title={running ? 'Waiting for the first document to finish' : 'This run recorded no trials'}
              hint={running ? 'A plan set takes minutes per document. The page polls every 2 seconds.' : 'Nothing was extracted — check the run error above, or the API log.'}
            />
          ) : (
            <>
              <div style={css('display:flex;align-items:center;gap:10px;padding:7px 12px;border-bottom:1px solid var(--border);background:var(--panel-2)')}>
                <span style={css('font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)')}>
                  Per document · worst first
                </span>
                <span style={css('flex:1')} />
                <label style={css('display:flex;align-items:center;gap:6px;font-size:11.5px;color:var(--text-2);cursor:pointer')}>
                  <input type="checkbox" checked={problemsOnly} onChange={(e) => setProblemsOnly(e.target.checked)} />
                  only documents with something to fix
                </label>
              </div>

              {shown.length === 0 ? (
                <Empty title="Every document in this run came back clean" hint="Uncheck the filter to see the full list." />
              ) : (
                shown.map((t) => {
                  const doc = docs.get(t.doc_id)
                  const isOpen = !!open[t.id]
                  return (
                    <div key={t.id} style={css('border-bottom:1px solid var(--border)')}>
                      <Box
                        as="button" type="button"
                        onClick={() => setOpen((o) => ({ ...o, [t.id]: !o[t.id] }))}
                        css="width:100%;display:flex;align-items:center;gap:10px;padding:8px 12px;text-align:left"
                        hover="background:var(--primary-softer)"
                      >
                        <span style={css(`color:var(--text-3);font-size:10px;width:10px;transform:rotate(${isOpen ? 90 : 0}deg)`)}>▶</span>
                        <span style={css('min-width:0;flex:1')}>
                          <span style={css('display:flex;align-items:center;gap:7px')}>
                            <span style={css('font-family:var(--mono);font-size:12px;font-weight:600')}>{t.doc_id}</span>
                            {run.trials > 1 ? <span style={badge('gray')}>trial {t.trial_index + 1}</span> : null}
                            {t.mocked ? <span style={badge('danger')}>MOCKED</span> : null}
                            {t.error ? <span style={badge('danger')}>failed</span> : null}
                          </span>
                          <span style={css('display:block;font-size:11.5px;color:var(--text-3);margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>
                            {doc?.title || 'not in the current manifest'}
                            {t.score?.completeness ? ` · ${t.score.completeness} truth` : ''}
                          </span>
                        </span>
                        <Counts trial={t} />
                        <span style={css('width:66px;flex:none;text-align:right')}>
                          <span style={css('display:block;font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)')}>recall</span>
                          <span style={css('font-family:var(--mono);font-size:13px;font-weight:600')}>{metric(t.score?.recall)}</span>
                        </span>
                        <span style={css('width:66px;flex:none;text-align:right')}>
                          <span style={css('display:block;font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)')}>prec</span>
                          <span style={css('font-family:var(--mono);font-size:13px;font-weight:600')}>{metric(t.score?.precision)}</span>
                        </span>
                        <span style={css('width:60px;flex:none;text-align:right;font-family:var(--mono);font-size:11.5px;color:var(--text-3)')}>
                          {ms(t.latency_ms)}
                        </span>
                      </Box>
                      {isOpen ? <DocDiff trial={t} /> : null}
                    </div>
                  )
                })
              )}
            </>
          )}
        </div>
      )}
    </Panel>
  )
}
