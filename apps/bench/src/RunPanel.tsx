import { Btn, Empty, Panel, badge, css, num } from './lib'
import type { CorpusDocOut, PlanTypeOut, StatusOut, VariantOut } from './types'

// Starting a run costs real, slow, paid model calls against real plan sets, so
// this panel's job is to be explicit about the size of what you are about to do
// and to refuse when the result could not be an accuracy number anyway.

export default function RunPanel({
  status, planTypes, variants, docs, selectedDocs,
  planType, onPlanType, variantIds, onVariantIds, trials, onTrials, notes, onNotes,
  onRun, starting, error,
}: {
  status: StatusOut | null
  planTypes: PlanTypeOut[]
  variants: VariantOut[]
  docs: Map<string, CorpusDocOut>
  selectedDocs: string[]
  planType: string
  onPlanType: (v: string) => void
  variantIds: string[]
  onVariantIds: (v: string[]) => void
  trials: number
  onTrials: (v: number) => void
  notes: string
  onNotes: (v: string) => void
  onRun: () => void
  starting: boolean
  error: string | null
}) {
  const extractions = selectedDocs.length * Math.max(variantIds.length, 0) * Math.max(trials, 0)
  const unlabelled = selectedDocs.filter((id) => docs.get(id)?.has_truth === false)
  const live = status?.live_extraction !== false

  const blocked =
    !status ? 'The bench API has not answered yet — start it on :8040.'
    : !live ? 'No OpenAI key on the API process, so every extraction would come back mocked. A mocked run cannot produce an accuracy number: set PROCUREAI_OPENAI_API_KEY and restart the API.'
    : selectedDocs.length === 0 ? 'Select at least one corpus document on the left.'
    : variantIds.length === 0 ? 'Select at least one variant. "baseline" is the live configuration, unmodified.'
    : trials < 1 ? 'Trials must be at least 1.'
    : null

  const inputCss = 'height:28px;padding:0 8px;border-radius:6px;border:1px solid var(--border-strong);background:var(--panel);font-size:12.5px'
  const labelCss = 'font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3);display:block;margin-bottom:4px'

  const toggleVariant = (id: string) => {
    onVariantIds(variantIds.includes(id) ? variantIds.filter((v) => v !== id) : [...variantIds, id])
  }

  return (
    <Panel title="Run" subtitle="one run row per variant" style="flex:1;min-width:340px;min-height:0" bodyStyle="padding:10px 12px">
      <div style={css('display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start')}>
        <div style={css('min-width:150px')}>
          <label style={css(labelCss)}>Plan type</label>
          <select style={css(`${inputCss};width:100%`)} value={planType} onChange={(e) => onPlanType(e.target.value)}>
            <option value="">each doc’s own type</option>
            {planTypes.map((p) => (
              <option key={p.key} value={p.key} disabled={!p.enabled}>
                {p.label}{p.enabled ? '' : ' (disabled)'}
              </option>
            ))}
          </select>
        </div>
        <div style={css('width:78px')}>
          <label style={css(labelCss)}>Trials</label>
          <input
            style={css(`${inputCss};width:100%`)}
            type="number" min={1} max={20} value={trials}
            onChange={(e) => onTrials(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
          />
        </div>
        <div style={css('flex:1;min-width:170px')}>
          <label style={css(labelCss)}>Notes (batch label)</label>
          <input
            style={css(`${inputCss};width:100%`)}
            placeholder="what this run is testing"
            value={notes}
            onChange={(e) => onNotes(e.target.value)}
          />
        </div>
      </div>

      <div style={css('margin-top:10px')}>
        <label style={css(labelCss)}>Variants</label>
        {variants.length === 0 ? (
          <Empty
            title="No variants loaded"
            hint={<>Add JSON overlays under <code>bench-corpus/variants/</code>. <code>baseline</code> is synthesised even with no files, so an empty list here means the API could not read the corpus directory.</>}
          />
        ) : (
          <div style={css('display:flex;flex-wrap:wrap;gap:6px')}>
            {variants.map((v) => {
              const on = variantIds.includes(v.id)
              return (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => toggleVariant(v.id)}
                  title={v.description || undefined}
                  style={css(
                    `display:flex;flex-direction:column;align-items:flex-start;gap:1px;padding:6px 9px;border-radius:7px;text-align:left;max-width:230px;border:1px solid ${on ? 'var(--primary)' : 'var(--border-strong)'};background:${on ? 'var(--primary-soft)' : 'var(--panel)'}`,
                  )}
                >
                  <span style={css(`font-family:var(--mono);font-size:12px;font-weight:600;color:${on ? 'var(--primary-2)' : 'var(--text)'}`)}>
                    {v.id}
                  </span>
                  <span style={css('font-size:11px;color:var(--text-3);line-height:1.35')}>{v.label}</span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* Cost discipline: say the size of the job before it starts, in extractions. */}
      <div style={css('margin-top:12px;border-top:1px solid var(--border);padding-top:10px')}>
        <div style={css('font-size:13px;line-height:1.5')}>
          {extractions > 0 ? (
            <>
              This will perform{' '}
              <strong style={css('font-family:var(--mono);font-size:15px')}>{num(extractions)}</strong>{' '}
              extraction{extractions === 1 ? '' : 's'} —{' '}
              <span style={css('font-family:var(--mono)')}>
                {selectedDocs.length} doc{selectedDocs.length === 1 ? '' : 's'} × {variantIds.length} variant
                {variantIds.length === 1 ? '' : 's'} × {trials} trial{trials === 1 ? '' : 's'}
              </span>
              .
              <span style={css('color:var(--text-2)')}> Each one is a real model call over a full plan set: minutes of wall clock, and billed.</span>
            </>
          ) : (
            <span style={css('color:var(--text-2)')}>Select documents and at least one variant to size the run.</span>
          )}
        </div>

        {unlabelled.length ? (
          <div style={css('margin-top:6px;font-size:11.5px;color:var(--warn)')}>
            {unlabelled.length} selected document{unlabelled.length === 1 ? ' has' : 's have'} no ground truth
            ({unlabelled.join(', ')}) — {unlabelled.length === 1 ? 'it' : 'they'} will run and be timed, but not scored.
          </div>
        ) : null}

        {blocked ? (
          <div style={css('margin-top:8px;font-size:11.5px;color:var(--text-2);background:var(--panel-2);border:1px solid var(--border);border-radius:7px;padding:7px 9px;line-height:1.5')}>
            {blocked}
          </div>
        ) : null}

        {error ? (
          <div style={css('margin-top:8px;font-size:12px;color:var(--danger);background:var(--danger-soft);border-radius:7px;padding:7px 9px')}>
            {error}
          </div>
        ) : null}

        <div style={css('margin-top:10px;display:flex;align-items:center;gap:10px')}>
          <Btn kind="primary" onClick={onRun} disabled={!!blocked || starting} style="height:32px;padding:0 16px;font-size:13px">
            {starting ? 'Starting…' : `Run ${extractions || ''} extraction${extractions === 1 ? '' : 's'}`.trim()}
          </Btn>
          {status && !live ? <span style={badge('danger')}>results would be MOCKED</span> : null}
          <span style={css('font-size:11px;color:var(--text-3)')}>Nothing runs until you press this.</span>
        </div>
      </div>
    </Panel>
  )
}
