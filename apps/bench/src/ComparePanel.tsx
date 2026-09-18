import { Empty, Panel, badge, ago, css, delta, metric, num, runMetrics } from './lib'
import { METRIC_LABELS } from './types'
import type { CompareOut, DocScoreOut, MetricKey, RunSummaryOut } from './types'

// Run vs run. Deltas are computed from the two summaries the endpoint returns,
// so the direction shown always matches the numbers next to it; the API's own
// `deltas` block is used only as a cross-check.

const ROWS: MetricKey[] = ['precision', 'recall', 'f1', 'quantity_accuracy', 'unit_accuracy', 'category_accuracy']

function dirColour(d: number | null, higherIsBetter = true): string {
  if (d === null || d === 0) return 'var(--text-3)'
  const good = higherIsBetter ? d > 0 : d < 0
  return good ? 'var(--success)' : 'var(--danger)'
}

function diffOf(a: number | null | undefined, b: number | null | undefined): number | null {
  return typeof a === 'number' && typeof b === 'number' ? b - a : null
}

function Head({ run, slot }: { run: RunSummaryOut; slot: string }) {
  const mocked = (run.mocked_trials || 0) > 0
  return (
    <div style={css('flex:1;min-width:0')}>
      <div style={css('display:flex;align-items:center;gap:6px')}>
        <span style={badge(slot === 'A' ? 'gray' : 'blue')}>{slot}</span>
        <span style={css('font-family:var(--mono);font-size:13px;font-weight:700')}>{run.variant_id}</span>
        {mocked ? <span style={badge('danger')}>MOCKED</span> : null}
      </div>
      <div style={css('font-size:11px;color:var(--text-3);margin-top:2px;font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>
        {run.id}
      </div>
      <div style={css('font-size:11.5px;color:var(--text-2);margin-top:2px')}>
        {ago(run.created_at)} · {run.doc_ids.length}×{run.trials}{run.notes ? ` · ${run.notes}` : ''}
      </div>
    </div>
  )
}

// Which concrete items changed state between the two runs. The metric row says
// recall moved; this says *which item* started or stopped being found, which is
// the only form in which the answer is useful.
function movement(a: DocScoreOut | null, b: DocScoreOut | null) {
  const names = (s: DocScoreOut | null, kind: string) =>
    new Set((s?.matches || []).filter((m) => m.kind === kind).map((m) => m.truth_name || m.extracted_name || '').filter(Boolean))
  const hitA = names(a, 'hit')
  const hitB = names(b, 'hit')
  const missA = names(a, 'miss')
  const missB = names(b, 'miss')
  const forbA = names(a, 'forbidden')
  const forbB = names(b, 'forbidden')
  return {
    found: [...missA].filter((n) => hitB.has(n)),
    lost: [...missB].filter((n) => hitA.has(n)),
    newHallucinations: [...forbB].filter((n) => !forbA.has(n)),
    fixedHallucinations: [...forbA].filter((n) => !forbB.has(n)),
  }
}

function ItemList({ label, items, colour, glyph }: { label: string; items: string[]; colour: string; glyph: string }) {
  if (!items.length) return null
  return (
    <div style={css('margin-top:4px')}>
      <div style={css(`font-size:11px;font-weight:700;color:${colour}`)}>{glyph} {label} ({items.length})</div>
      <ul style={css('margin:2px 0 0;padding-left:18px;font-size:11.5px;color:var(--text-2);line-height:1.5')}>
        {items.map((n) => <li key={n} style={css('font-family:var(--mono)')}>{n}</li>)}
      </ul>
    </div>
  )
}

export default function ComparePanel({
  data, loading, error, aId, bId,
}: {
  data: CompareOut | null
  loading: boolean
  error: string | null
  aId: string | null
  bId: string | null
}) {
  if (!aId || !bId || aId === bId) {
    return (
      <Panel title="Compare" style="flex:1;min-height:0">
        <Empty
          title="Pin two different runs"
          hint="Use the A and B buttons in the Runs list. Compare is how a variant is judged better than the baseline — same documents, same trial count, one thing changed."
        />
      </Panel>
    )
  }

  if (error) {
    return (
      <Panel title="Compare" style="flex:1;min-height:0">
        <Empty title="Could not compare these runs" hint={error} />
      </Panel>
    )
  }

  if (!data) {
    return (
      <Panel title="Compare" style="flex:1;min-height:0">
        <Empty title={loading ? 'Comparing…' : 'No comparison yet'} />
      </Panel>
    )
  }

  const { a, b } = data
  const ma = runMetrics(a)
  const mb = runMetrics(b)
  const sharedDocs = data.per_doc.length
  const perDoc = data.per_doc
    .map((p) => ({ ...p, d: diffOf(p.a?.recall, p.b?.recall), move: movement(p.a, p.b) }))
    .sort((x, y) => Math.abs(y.d ?? 0) - Math.abs(x.d ?? 0))

  const sameShape = a.doc_ids.length === b.doc_ids.length && a.trials === b.trials

  return (
    <Panel
      title="Compare"
      subtitle={`${a.variant_id} → ${b.variant_id}`}
      style="flex:1;min-height:0"
    >
      <div style={css('display:flex;gap:16px;padding:12px;border-bottom:1px solid var(--border)')}>
        <Head run={a} slot="A" />
        <span style={css('color:var(--text-3);font-size:18px;align-self:center')}>→</span>
        <Head run={b} slot="B" />
      </div>

      {!sameShape ? (
        <div style={css('padding:8px 12px;background:var(--warn-soft);color:var(--warn);font-size:11.5px;border-bottom:1px solid var(--border)')}>
          These runs do not have the same shape ({a.doc_ids.length} docs × {a.trials} vs {b.doc_ids.length} × {b.trials}).
          The deltas below are still arithmetic, but they are not a controlled comparison.
        </div>
      ) : null}

      {(a.mocked_trials || 0) > 0 || (b.mocked_trials || 0) > 0 ? (
        <div style={css('background:var(--danger);color:#fff;padding:8px 12px;font-size:12.5px;font-weight:600')}>
          MOCKED — at least one of these runs was extracted by the mock pipeline. Its numbers are not accuracy results and
          the delta below is meaningless.
        </div>
      ) : null}

      <table style={css('width:100%;border-collapse:collapse;font-size:12.5px')}>
        <thead>
          <tr style={css('background:var(--panel-2)')}>
            {['Metric', 'A', 'B', 'Δ'].map((h, i) => (
              <th key={h} style={css(`text-align:${i === 0 ? 'left' : 'right'};padding:6px 12px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3);border-bottom:1px solid var(--border)`)}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((k) => {
            const d = diffOf(ma?.[k], mb?.[k])
            return (
              <tr key={k}>
                <td style={css('padding:5px 12px;border-bottom:1px solid var(--border)')}>{METRIC_LABELS[k]}</td>
                <td style={css('padding:5px 12px;text-align:right;font-family:var(--mono);border-bottom:1px solid var(--border)')}>{metric(ma?.[k])}</td>
                <td style={css('padding:5px 12px;text-align:right;font-family:var(--mono);border-bottom:1px solid var(--border)')}>{metric(mb?.[k])}</td>
                <td style={css(`padding:5px 12px;text-align:right;font-family:var(--mono);font-weight:600;color:${dirColour(d)};border-bottom:1px solid var(--border)`)}>
                  {delta(ma?.[k], mb?.[k])}
                </td>
              </tr>
            )
          })}
          <tr>
            <td style={css('padding:5px 12px;border-bottom:1px solid var(--border)')}>Hallucinations</td>
            <td style={css('padding:5px 12px;text-align:right;font-family:var(--mono);border-bottom:1px solid var(--border)')}>{num(ma?.hallucinations)}</td>
            <td style={css('padding:5px 12px;text-align:right;font-family:var(--mono);border-bottom:1px solid var(--border)')}>{num(mb?.hallucinations)}</td>
            <td style={css(`padding:5px 12px;text-align:right;font-family:var(--mono);font-weight:600;color:${dirColour(diffOf(ma?.hallucinations, mb?.hallucinations), false)};border-bottom:1px solid var(--border)`)}>
              {delta(ma?.hallucinations, mb?.hallucinations, 0)}
            </td>
          </tr>
        </tbody>
      </table>

      <div style={css('padding:8px 12px;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3);background:var(--panel-2);border-top:1px solid var(--border);border-bottom:1px solid var(--border)')}>
        Documents that moved
      </div>

      {sharedDocs === 0 ? (
        <Empty title="These runs share no scored documents" hint="Compare is only meaningful across the same corpus selection." />
      ) : (
        perDoc.map((p) => {
          const nothing = p.d === 0 || p.d === null
          const noItems = !p.move.found.length && !p.move.lost.length && !p.move.newHallucinations.length && !p.move.fixedHallucinations.length
          return (
            <div key={p.doc_id} style={css('padding:8px 12px;border-bottom:1px solid var(--border)')}>
              <div style={css('display:flex;align-items:center;gap:10px')}>
                <span style={css('font-family:var(--mono);font-size:12px;font-weight:600;flex:1;min-width:0')}>{p.doc_id}</span>
                <span style={css('font-family:var(--mono);font-size:11.5px;color:var(--text-2)')}>
                  recall {metric(p.a?.recall)} → {metric(p.b?.recall)}
                </span>
                <span style={css(`font-family:var(--mono);font-size:12px;font-weight:700;width:56px;text-align:right;color:${dirColour(p.d)}`)}>
                  {delta(p.a?.recall, p.b?.recall)}
                </span>
              </div>
              {nothing && noItems ? (
                <div style={css('font-size:11.5px;color:var(--text-3);margin-top:2px')}>
                  {p.a && p.b ? 'No change.' : 'Only scored in one of the two runs.'}
                </div>
              ) : null}
              <ItemList label="now found" items={p.move.found} colour="var(--success)" glyph="✓" />
              <ItemList label="no longer found" items={p.move.lost} colour="var(--danger)" glyph="✗" />
              <ItemList label="new hallucinations" items={p.move.newHallucinations} colour="var(--danger)" glyph="!" />
              <ItemList label="hallucinations fixed" items={p.move.fixedHallucinations} colour="var(--success)" glyph="✓" />
            </div>
          )
        })
      )}
    </Panel>
  )
}
