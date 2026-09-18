import { useState } from 'react'
import { Box, Btn, Empty, badge, css, metric, num, qty } from './lib'
import type { DocScoreOut, ItemMatchOut, TrialOut } from './types'

// The per-document diff — the reason this tool exists.
//
// A headline like "recall .74" is not actionable; what a prompt or spec change
// needs is the concrete list: which items were missed, which were invented,
// which matched but with the wrong number. Every row is laid out as the same
// "got vs want" comparison so the eye can run down one column.

type SectionKey = 'miss' | 'quantity' | 'forbidden' | 'attribute' | 'extra' | 'unknown' | 'hit'

type Section = {
  key: SectionKey
  title: string
  glyph: string
  tone: string
  colour: string
  /** What this bucket means for tuning — shown above the rows. */
  hint: string
  rows: ItemMatchOut[]
  openByDefault: boolean
}

function bucket(score: DocScoreOut): Section[] {
  const m = score.matches
  const hits = m.filter((x) => x.kind === 'hit')
  const wrongQty = hits.filter((x) => x.quantity_ok === false)
  const wrongAttr = hits.filter((x) => x.quantity_ok !== false && (x.category_ok === false || x.unit_ok === false))
  const clean = hits.filter((x) => !wrongQty.includes(x) && !wrongAttr.includes(x))
  const partial = score.completeness === 'partial'

  return [
    {
      key: 'miss', title: 'Missed', glyph: '✗', tone: 'danger', colour: 'var(--danger)',
      hint: 'In the ground truth, absent from the extraction. This is what recall is measuring — the first thing a prompt change should move.',
      rows: m.filter((x) => x.kind === 'miss'), openByDefault: true,
    },
    {
      key: 'quantity', title: 'Wrong quantity', glyph: '≠', tone: 'warn', colour: 'var(--warn)',
      hint: 'The right item, the wrong number — outside the truth item\'s tolerance. Usually a counting/summing problem, not a naming one.',
      rows: wrongQty, openByDefault: true,
    },
    {
      key: 'forbidden', title: 'Hallucinated', glyph: '!', tone: 'danger', colour: 'var(--danger)',
      hint: 'Matched an item the truth file explicitly forbids (legend symbols, design alternates). A hard error at any accuracy level.',
      rows: m.filter((x) => x.kind === 'forbidden'), openByDefault: true,
    },
    {
      key: 'attribute', title: 'Wrong category or unit', glyph: '~', tone: 'warn', colour: 'var(--warn)',
      hint: 'Found and counted correctly, but filed under the wrong category or reported in the wrong unit. A smaller failure than a miss — it is a spec/label problem.',
      rows: wrongAttr, openByDefault: true,
    },
    {
      key: 'extra', title: 'Extra', glyph: '+', tone: 'warn', colour: 'var(--warn)',
      hint: 'Extracted with no truth counterpart, on a fully-labelled document — a false positive, and what precision is measuring.',
      rows: m.filter((x) => x.kind === 'extra'), openByDefault: true,
    },
    {
      key: 'unknown', title: 'Unscored extras', glyph: '?', tone: 'gray', colour: 'var(--text-3)',
      hint: partial
        ? 'Extracted with no truth counterpart on a partially-labelled document. Not counted against precision — the truth may simply not cover it. Worth reading: real finds here are truth-file work.'
        : 'Extracted with no truth counterpart and not scored either way.',
      rows: m.filter((x) => x.kind === 'unknown'), openByDefault: false,
    },
    {
      // Named "fully correct" because the row's ✓ badge counts every hit,
      // including the ones broken out above as wrong-quantity or wrong-unit.
      key: 'hit', title: 'Fully correct', glyph: '✓', tone: 'success', colour: 'var(--success)',
      hint: 'Matched the truth on name, quantity, unit and category.',
      rows: clean, openByDefault: false,
    },
  ]
}

function got(m: ItemMatchOut): string {
  if (m.kind === 'miss') return 'not extracted'
  if (m.quantity_got === null || m.quantity_got === undefined) {
    return m.extracted_display || (m.unit_got ? `— ${m.unit_got}` : '—')
  }
  return qty(m.quantity_got, m.unit_got)
}

function want(m: ItemMatchOut): string {
  if (m.kind === 'extra' || m.kind === 'unknown') return 'not in truth'
  if (m.kind === 'forbidden') return 'forbidden'
  return qty(m.quantity_want, m.unit_want)
}

// "+38%" — how far off the quantity is, which is the number that says whether
// this is a rounding disagreement or a whole missed sheet.
function drift(m: ItemMatchOut): string | null {
  const g = m.quantity_got
  const w = m.quantity_want
  if (g === null || g === undefined || w === null || w === undefined || w === 0) return null
  const d = (g - w) / w
  return `${d > 0 ? '+' : '−'}${Math.abs(d * 100).toFixed(0)}%`
}

const CELL = 'font-family:var(--mono);font-size:11.5px;white-space:nowrap'

function Row({ m, section }: { m: ItemMatchOut; section: Section }) {
  const name = m.truth_name || m.extracted_name || '(unnamed)'
  const alt = m.truth_name && m.extracted_name && m.truth_name !== m.extracted_name ? m.extracted_name : null
  const d = section.key === 'quantity' ? drift(m) : null
  const optional = m.required === false

  return (
    <div style={css('display:flex;align-items:flex-start;gap:10px;padding:6px 12px 6px 14px;border-top:1px solid var(--border)')}>
      <span style={css(`color:${section.colour};font-weight:700;font-size:12px;width:12px;flex:none;line-height:1.5`)}>{section.glyph}</span>

      <div style={css('flex:1;min-width:0')}>
        <div style={css('font-size:12.5px;font-weight:600;line-height:1.45;word-break:break-word')}>
          {name}
          {optional ? <span style={badge('gray', { marginLeft: 6 })}>optional</span> : null}
          {m.category_ok === false ? (
            <span style={badge('warn', { marginLeft: 6 })}>
              {m.extracted_category || m.truth_category
                ? `category ${m.extracted_category || '—'} → ${m.truth_category || '—'}`
                : 'wrong category'}
            </span>
          ) : null}
          {m.unit_ok === false ? (
            <span style={badge('warn', { marginLeft: 6 })}>
              unit {m.unit_got || '—'} → {m.unit_want || '—'}
            </span>
          ) : null}
        </div>
        {alt ? (
          <div style={css('font-size:11.5px;color:var(--text-3);margin-top:2px;font-family:var(--mono)')}>
            extracted as “{alt}” · match {metric(m.score)}
          </div>
        ) : null}
        {m.forbidden_why ? (
          <div style={css('font-size:11.5px;color:var(--danger);margin-top:2px')}>why forbidden: {m.forbidden_why}</div>
        ) : null}
        {m.truth_source && (section.key === 'miss' || section.key === 'quantity') ? (
          <div style={css('font-size:11.5px;color:var(--text-3);margin-top:2px')}>truth source: {m.truth_source}</div>
        ) : null}
      </div>

      <div style={css('width:150px;flex:none;text-align:right')}>
        <div style={css('font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)')}>got</div>
        <div style={css(`${CELL};color:${m.kind === 'miss' ? 'var(--text-3)' : 'var(--text)'}`)}>{got(m)}</div>
      </div>
      <div style={css('width:150px;flex:none;text-align:right')}>
        <div style={css('font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)')}>want</div>
        <div style={css(`${CELL};color:${m.kind === 'extra' || m.kind === 'unknown' ? 'var(--text-3)' : 'var(--text)'}`)}>{want(m)}</div>
      </div>
      <div style={css('width:78px;flex:none;text-align:right')}>
        {d ? (
          <>
            <div style={css('font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)')}>off by</div>
            <div style={css(`${CELL};color:var(--warn);font-weight:600`)}>{d}</div>
          </>
        ) : null}
        {section.key === 'quantity' && m.qty_tolerance ? (
          <div style={css('font-size:10px;color:var(--text-3)')}>tol ±{Math.round(m.qty_tolerance * 100)}%</div>
        ) : null}
      </div>
    </div>
  )
}

function SectionBlock({ section }: { section: Section }) {
  const [open, setOpen] = useState(section.openByDefault)
  if (!section.rows.length) return null
  return (
    <div style={css('border:1px solid var(--border);border-left:3px solid ' + section.colour + ';border-radius:8px;overflow:hidden;background:var(--panel)')}>
      <Box
        as="button" type="button" onClick={() => setOpen(!open)}
        css="width:100%;display:flex;align-items:center;gap:8px;padding:7px 12px;text-align:left;background:var(--panel-2)"
        hover="background:var(--panel-3)"
      >
        <span style={css(`color:${section.colour};font-weight:700;font-size:12px;width:12px`)}>{section.glyph}</span>
        <span style={css('font-size:12.5px;font-weight:700')}>{section.title}</span>
        <span style={badge(section.tone)}>{section.rows.length}</span>
        <span style={css('flex:1')} />
        <span style={css('font-size:11px;color:var(--text-3)')}>{open ? 'hide' : 'show'}</span>
      </Box>
      {open ? (
        <>
          <div style={css('padding:7px 12px 8px 29px;font-size:11.5px;color:var(--text-2);line-height:1.5;background:var(--panel-2);border-top:1px solid var(--border)')}>
            {section.hint}
          </div>
          {section.rows.map((m, i) => (
            <Row key={`${section.key}-${i}`} m={m} section={section} />
          ))}
        </>
      ) : null}
    </div>
  )
}

// Markdown of the diff, for pasting straight into a prompt/spec tuning session.
function asMarkdown(trial: TrialOut, sections: Section[]): string {
  const lines = [`## ${trial.doc_id} — variant \`${trial.variant_id}\`${trial.mocked ? ' (MOCKED EXTRACTION — not an accuracy result)' : ''}`]
  for (const s of sections) {
    if (!s.rows.length || s.key === 'hit') continue
    lines.push('', `### ${s.title} (${s.rows.length})`)
    for (const m of s.rows) {
      lines.push(`- ${m.truth_name || m.extracted_name} — got ${got(m)}, want ${want(m)}`)
    }
  }
  return lines.join('\n')
}

export default function DocDiff({ trial }: { trial: TrialOut }) {
  const [copied, setCopied] = useState<'idle' | 'done' | 'failed'>('idle')

  if (trial.error) {
    return (
      <div style={css('padding:12px')}>
        <div style={css('border:1px solid var(--danger);background:var(--danger-soft);border-radius:8px;padding:10px 12px;font-size:12.5px;color:var(--danger)')}>
          <strong>Extraction failed.</strong> {trial.error}
        </div>
      </div>
    )
  }

  if (!trial.score) {
    const extracted = (trial.groups || []).reduce((a, g) => a + g.items.length, 0)
    return (
      <div style={css('padding:4px 12px 12px')}>
        <Empty
          title="No ground truth for this document"
          hint={
            <>
              The extraction ran{extracted ? ` and returned ${num(extracted)} item${extracted === 1 ? '' : 's'}` : ''}, but nothing scored it.
              Add <code>bench-corpus/truth/{trial.doc_id}.json</code> and point the manifest entry’s{' '}
              <code>truth</code> field at it, then re-run.
            </>
          }
        />
        {trial.groups?.length ? (
          <div style={css('margin-top:2px')}>
            <div style={css('font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3);margin-bottom:6px')}>
              What it extracted
            </div>
            {trial.groups.map((g) => (
              <div key={g.group} style={css('margin-bottom:8px')}>
                <div style={css('font-size:12px;font-weight:700;margin-bottom:3px')}>{g.group} <span style={css('color:var(--text-3);font-weight:500')}>({g.count})</span></div>
                {g.items.map((it, i) => (
                  <div key={i} style={css('display:flex;gap:10px;font-size:11.5px;font-family:var(--mono);padding:1px 0')}>
                    <span style={css('flex:1;min-width:0')}>{it.n}</span>
                    <span style={css('color:var(--text-2)')}>{it.q}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    )
  }

  const sections = bucket(trial.score)
  const actionable = sections.filter((s) => s.key !== 'hit').reduce((a, s) => a + s.rows.length, 0)

  return (
    <div style={css('padding:10px 12px 14px;background:var(--panel-2);display:flex;flex-direction:column;gap:8px')}>
      <div style={css('display:flex;align-items:center;gap:8px')}>
        <span style={css('font-size:11.5px;color:var(--text-2)')}>
          {actionable === 0
            ? 'Nothing to fix on this document — every truth item matched.'
            : `${num(actionable)} item${actionable === 1 ? '' : 's'} to look at.`}
        </span>
        <span style={css('flex:1')} />
        <Btn
          onClick={() => {
            const text = asMarkdown(trial, sections)
            const clip = navigator.clipboard
            if (!clip) { setCopied('failed'); return }
            clip.writeText(text).then(() => setCopied('done'), () => setCopied('failed'))
          }}
          title="Paste straight into a prompt or spec tuning session."
        >
          {copied === 'done' ? 'Copied' : copied === 'failed' ? 'Clipboard blocked' : 'Copy diff as markdown'}
        </Btn>
      </div>

      {/* Say why the empty cells are empty, or a `—` reads as a broken UI. */}
      {trial.score.completeness === 'partial' ? (
        <div style={css('font-size:11.5px;color:var(--text-2);line-height:1.5;border:1px solid var(--border);border-radius:8px;padding:8px 11px;background:var(--panel)')}>
          This document’s ground truth is <strong>partial</strong> — only the listed items are verified. Precision and F1
          are therefore undefined (<span style={css('font-family:var(--mono)')}>—</span>) rather than low: an extracted
          item with no truth match is <strong>unscored</strong>, not a false positive. Recall and the quantity/unit/category
          numbers are still real.
        </div>
      ) : null}

      {sections.map((s) => (
        <SectionBlock key={s.key} section={s} />
      ))}

      {trial.summary_text ? (
        <div style={css('font-size:11.5px;color:var(--text-2);line-height:1.5;border:1px solid var(--border);border-radius:8px;padding:9px 12px;background:var(--panel)')}>
          <strong style={css('font-weight:700')}>Model summary:</strong> {trial.summary_text}
        </div>
      ) : null}
    </div>
  )
}
