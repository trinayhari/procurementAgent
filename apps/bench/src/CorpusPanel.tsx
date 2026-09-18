import { useMemo, useState } from 'react'
import { Box, Btn, Empty, Panel, badge, bytes, css, num } from './lib'
import type { CorpusOut, PlanTypeOut } from './types'

// The corpus checkbox list. Selection is the only state it owns; running is the
// Run panel's job, and nothing here triggers an extraction.

export default function CorpusPanel({
  corpus, planTypes, selected, onChange, loading, error,
}: {
  corpus: CorpusOut | null
  planTypes: PlanTypeOut[]
  selected: Set<string>
  onChange: (next: Set<string>) => void
  loading: boolean
  error: string | null
}) {
  const [planFilter, setPlanFilter] = useState('')
  const [labelledOnly, setLabelledOnly] = useState(false)
  const [q, setQ] = useState('')

  const docs = corpus?.documents || []
  const visible = useMemo(
    () =>
      docs.filter((d) => {
        if (planFilter && d.plan_type !== planFilter) return false
        if (labelledOnly && !d.has_truth) return false
        if (q && !(`${d.id} ${d.title} ${d.tags.join(' ')}`.toLowerCase().includes(q.toLowerCase()))) return false
        return true
      }),
    [docs, planFilter, labelledOnly, q],
  )

  // A doc whose PDF is not on this machine cannot be extracted, so it is never
  // selectable — better than failing every trial a minute into the run.
  const runnable = visible.filter((d) => d.exists)
  const allSelected = runnable.length > 0 && runnable.every((d) => selected.has(d.id))

  const toggle = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(next)
  }

  const toggleAll = () => {
    const next = new Set(selected)
    if (allSelected) runnable.forEach((d) => next.delete(d.id))
    else runnable.forEach((d) => next.add(d.id))
    onChange(next)
  }

  const inputCss = 'height:26px;padding:0 8px;border-radius:6px;border:1px solid var(--border-strong);background:var(--panel);font-size:12px'

  return (
    <Panel
      title="Corpus"
      subtitle={corpus ? `${num(docs.length)} docs · ${num(docs.filter((d) => d.has_truth).length)} labelled` : undefined}
      right={
        <span style={css('display:flex;align-items:center;gap:6px')}>
          <span style={css('font-size:11.5px;color:var(--text-2)')}>{selected.size} selected</span>
          {selected.size ? <Btn onClick={() => onChange(new Set())}>Clear</Btn> : null}
        </span>
      }
      style="flex:0 0 340px;min-height:0"
    >
      {error ? (
        <Empty
          title="Could not load the corpus"
          hint={
            <>
              {error}
              <br />
              Start the bench API on :8040 (<code>bench-api</code> in launch.json) and confirm{' '}
              <code>settings.bench_enabled</code> is true outside production.
            </>
          }
        />
      ) : loading ? (
        <Empty title="Loading corpus…" />
      ) : docs.length === 0 ? (
        <Empty
          title="No corpus documents"
          hint={
            <>
              <code>bench-corpus/manifest.json</code> has no entries (or does not exist yet). Add plan sets to the
              manifest with provenance and a license, then reload.
            </>
          }
        />
      ) : (
        <>
          <div style={css('display:flex;flex-wrap:wrap;gap:6px;padding:8px 10px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--panel);z-index:1')}>
            <input
              style={css(`${inputCss};flex:1;min-width:110px`)}
              placeholder="filter by id, title, tag"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select style={css(inputCss)} value={planFilter} onChange={(e) => setPlanFilter(e.target.value)}>
              <option value="">all plan types</option>
              {(planTypes.length ? planTypes.map((p) => [p.key, p.label] as const) : [...new Set(docs.map((d) => d.plan_type))].map((k) => [k, k] as const)).map(
                ([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ),
              )}
            </select>
            <label style={css('display:flex;align-items:center;gap:5px;font-size:11.5px;color:var(--text-2);cursor:pointer')}>
              <input type="checkbox" checked={labelledOnly} onChange={(e) => setLabelledOnly(e.target.checked)} />
              labelled only
            </label>
            <Btn onClick={toggleAll} disabled={!runnable.length}>
              {allSelected ? 'Deselect' : 'Select'} {planFilter ? planFilter : 'all'} ({runnable.length})
            </Btn>
          </div>

          {corpus?.problems.length ? (
            <div style={css('padding:8px 10px;border-bottom:1px solid var(--border);background:var(--warn-soft);color:var(--warn);font-size:11.5px;line-height:1.5')}>
              <strong>{corpus.problems.length} corpus problem{corpus.problems.length === 1 ? '' : 's'}</strong>
              <ul style={css('margin:4px 0 0;padding-left:16px')}>
                {corpus.problems.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </div>
          ) : null}

          {visible.length === 0 ? (
            <Empty title="No documents match this filter" hint="Clear the search box or the plan-type filter." />
          ) : (
            visible.map((d) => {
              const on = selected.has(d.id)
              return (
                <Box
                  key={d.id}
                  as="label"
                  css={`display:flex;gap:8px;padding:8px 10px;border-bottom:1px solid var(--border);cursor:${d.exists ? 'pointer' : 'not-allowed'};background:${on ? 'var(--primary-softer)' : 'transparent'}`}
                  hover={d.exists ? (on ? 'background:var(--primary-soft)' : 'background:var(--panel-2)') : undefined}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={!d.exists}
                    onChange={() => toggle(d.id)}
                    style={css('margin-top:2px;flex:none')}
                  />
                  <span style={css('min-width:0;flex:1')}>
                    <span style={css('display:flex;align-items:center;gap:6px;flex-wrap:wrap')}>
                      <span style={css('font-family:var(--mono);font-size:12px;font-weight:600')}>{d.id}</span>
                      <span style={badge('blue')}>{d.plan_type}</span>
                      {!d.has_truth ? <span style={badge('warn')} title="Runs fine, but nothing will score it.">no truth</span> : null}
                      {!d.exists ? <span style={badge('danger')}>PDF missing locally</span> : null}
                      {d.has_text_layer === false ? <span style={badge('gray')} title="Scanned — extraction falls back to vision.">no text layer</span> : null}
                    </span>
                    <span style={css('display:block;font-size:11.5px;color:var(--text-2);margin-top:2px;line-height:1.4')}>{d.title}</span>
                    <span style={css('display:block;font-size:11px;color:var(--text-3);margin-top:2px;font-family:var(--mono)')}>
                      {d.pages ? `${num(d.pages)}p` : '—'} · {bytes(d.bytes)} · {d.license}
                      {d.source_name ? ` · ${d.source_name}` : ''}
                    </span>
                    {!d.exists ? (
                      <span style={css('display:block;font-size:11px;color:var(--danger);margin-top:3px;line-height:1.45')}>
                        PDFs are gitignored. Fetch it with <code>python apps/api/scripts/fetch_corpus.py</code>, or drop the
                        file at <code>{d.path}</code>.
                      </span>
                    ) : null}
                    {!d.has_truth ? (
                      <span style={css('display:block;font-size:11px;color:var(--text-3);margin-top:3px;line-height:1.45')}>
                        Usable for latency and crash coverage only. Author{' '}
                        <code>bench-corpus/truth/{d.id}.json</code> to score it.
                      </span>
                    ) : null}
                  </span>
                </Box>
              )
            })
          )}
        </>
      )}
    </Panel>
  )
}
