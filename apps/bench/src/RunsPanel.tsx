import { Box, Btn, Empty, Panel, badge, ago, css, metric, runMetrics } from './lib'
import type { RunSummaryOut } from './types'

// Recent runs. Selecting one drives the Results panel; A/B pin the two runs the
// Compare panel diffs.

export default function RunsPanel({
  runs, selectedId, onSelect, compareA, compareB, onPin, loading, error, onRefresh,
}: {
  runs: RunSummaryOut[]
  selectedId: string | null
  onSelect: (id: string) => void
  compareA: string | null
  compareB: string | null
  onPin: (slot: 'a' | 'b', id: string) => void
  loading: boolean
  error: string | null
  onRefresh: () => void
}) {
  return (
    <Panel
      title="Runs"
      subtitle={runs.length ? `${runs.length} recent` : undefined}
      right={<Btn onClick={onRefresh}>{loading ? '…' : 'Refresh'}</Btn>}
      style="flex:0 0 290px;min-height:0"
    >
      {error ? (
        <Empty title="Could not list runs" hint={error} />
      ) : runs.length === 0 ? (
        <Empty
          title={loading ? 'Loading runs…' : 'No runs yet'}
          hint={loading ? undefined : 'Select corpus documents and a variant, then press Run. Runs are stored in the bench SQLite file, separate from the product database.'}
        />
      ) : (
        runs.map((r) => {
          const on = r.id === selectedId
          const running = r.status === 'running' || r.status === 'queued'
          const mocked = (r.mocked_trials || 0) > 0
          const m = runMetrics(r)
          return (
            <Box
              key={r.id}
              css={`border-bottom:1px solid var(--border);padding:7px 9px;background:${on ? 'var(--primary-softer)' : 'transparent'};border-left:3px solid ${on ? 'var(--primary)' : 'transparent'}`}
            >
              <Box
                as="button" type="button" onClick={() => onSelect(r.id)}
                css="width:100%;text-align:left;display:block"
              >
                <span style={css('display:flex;align-items:center;gap:6px;flex-wrap:wrap')}>
                  <span style={css('font-family:var(--mono);font-size:12px;font-weight:600')}>{r.variant_id}</span>
                  <span style={badge(r.status === 'done' ? 'success' : r.status === 'failed' ? 'danger' : running ? 'blue' : 'gray')}>
                    {running ? `${r.progress_done}/${r.progress_total}` : r.status}
                  </span>
                  {mocked ? <span style={badge('danger')}>MOCKED</span> : null}
                </span>
                <span style={css('display:block;font-size:11px;color:var(--text-3);margin-top:2px')}>
                  {ago(r.created_at)} · {r.doc_ids.length}×{r.trials}
                  {r.notes ? ` · ${r.notes}` : ''}
                </span>
                <span style={css('display:flex;gap:10px;margin-top:3px;font-family:var(--mono);font-size:11px;color:var(--text-2)')}>
                  <span>P {metric(m?.precision)}</span>
                  <span>R {metric(m?.recall)}</span>
                  <span>F1 {metric(m?.f1)}</span>
                </span>
              </Box>
              <span style={css('display:flex;gap:5px;margin-top:5px')}>
                {(['a', 'b'] as const).map((slot) => {
                  const pinned = (slot === 'a' ? compareA : compareB) === r.id
                  return (
                    <Box
                      key={slot}
                      as="button" type="button" onClick={() => onPin(slot, r.id)}
                      css={`height:20px;padding:0 8px;border-radius:5px;font-size:10.5px;font-weight:700;letter-spacing:.04em;border:1px solid ${pinned ? 'var(--primary)' : 'var(--border-strong)'};background:${pinned ? 'var(--primary)' : 'var(--panel)'};color:${pinned ? 'var(--on-primary)' : 'var(--text-3)'}`}
                      hover={pinned ? undefined : 'background:var(--panel-2)'}
                      title={`Pin as compare ${slot.toUpperCase()}`}
                    >
                      {slot.toUpperCase()}
                    </Box>
                  )
                })}
              </span>
            </Box>
          )
        })
      )}
    </Panel>
  )
}
