import { useState } from 'react'
import type { CSSProperties, ElementType, ReactNode } from 'react'
import type { RunMetrics, RunSummary } from './types'

// Same inline-style idiom as apps/web (see apps/web/src/lib.tsx): styles are
// written as CSS strings and converted here, so markup stays close to the
// design without a stylesheet or a component library. Deliberately a copy and
// not a shared package — the bench is a throwaway-able dev tool and must not
// become a reason the product app can't move.
export type StyleInput = string | CSSProperties

export function css(str?: string): CSSProperties {
  const o: Record<string, string> = {}
  if (!str) return o
  for (const part of str.split(';')) {
    const i = part.indexOf(':')
    if (i < 0) continue
    const k = part.slice(0, i).trim()
    const v = part.slice(i + 1).trim()
    if (!k) continue
    // Custom properties pass through as-is; camel-casing "--panel-2" would
    // mangle it into "-Panel-2" and the declaration would be dropped.
    o[k.startsWith('--') ? k : k.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())] = v
  }
  return o as CSSProperties
}

function toStyle(v?: StyleInput): CSSProperties {
  return typeof v === 'string' ? css(v) : v || {}
}

type BoxProps = {
  as?: ElementType
  css?: StyleInput
  hover?: StyleInput
  style?: StyleInput
  children?: ReactNode
} & Record<string, unknown>

// Polymorphic element with optional hover styles.
export function Box({ as = 'div', css: base, hover, style, children, ...rest }: BoxProps) {
  const [h, setH] = useState(false)
  const disabled = rest.disabled === true
  const merged: CSSProperties = {
    ...toStyle(base),
    ...toStyle(style),
    ...(h && hover && !disabled ? toStyle(hover) : {}),
  }
  const Tag = as
  const hoverProps = hover
    ? { onMouseEnter: () => setH(true), onMouseLeave: () => setH(false) }
    : {}
  return (
    <Tag style={merged} {...hoverProps} {...rest}>
      {children}
    </Tag>
  )
}

export type Tone = 'blue' | 'violet' | 'gray' | 'success' | 'warn' | 'danger'

export function tone(t: string): { bg: string; fg: string } {
  const M: Record<string, [string, string]> = {
    blue: ['var(--primary-soft)', 'var(--primary)'],
    violet: ['var(--violet-soft)', 'var(--violet)'],
    gray: ['var(--panel-3)', 'var(--text-2)'],
    success: ['var(--success-soft)', 'var(--success)'],
    warn: ['var(--warn-soft)', 'var(--warn)'],
    danger: ['var(--danger-soft)', 'var(--danger)'],
  }
  const [bg, fg] = M[t] || M.gray
  return { bg, fg }
}

export function badge(t: string, opts?: CSSProperties): CSSProperties {
  const { bg, fg } = tone(t)
  return {
    display: 'inline-flex', alignItems: 'center', gap: 4, padding: '1px 7px',
    borderRadius: 5, fontSize: 11, fontWeight: 600, background: bg, color: fg,
    whiteSpace: 'nowrap', lineHeight: 1.6, ...(opts || {}),
  }
}

// --- formatting -------------------------------------------------------------

// An undefined metric is `—`, never `0.00`: a measured zero and an unmeasurable
// metric are different facts (docs/eval-harness.md §2, scoring.py).
export function metric(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined ? '—' : v.toFixed(digits)
}

// The run summary nests its macro-averages under `metrics`, and keeps mocked
// trials in a separate `mocked_metrics` block. Read them through here so the
// nesting lives in one place — and so a mocked run can never leak its numbers
// into the accuracy display by way of a stray `summary.precision`.
export function runMetrics(run: { summary?: RunSummary | null } | null | undefined): RunMetrics | null {
  return run?.summary?.metrics ?? null
}

// Signed delta for the compare view; `—` when either side is undefined.
export function delta(a: number | null | undefined, b: number | null | undefined, digits = 2): string {
  if (a === null || a === undefined || b === null || b === undefined) return '—'
  const d = b - a
  return (d > 0 ? '+' : d < 0 ? '−' : '±') + Math.abs(d).toFixed(digits)
}

export function num(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

// "1,450 LF" from a numeric quantity + unit; "—" when the quantity is unknown.
export function qty(q: number | null | undefined, unit: string | null | undefined): string {
  if (q === null || q === undefined) return unit ? `— ${unit}` : '—'
  return unit ? `${num(q)} ${unit}` : num(q)
}

export function bytes(b: number | null | undefined): string {
  if (b === null || b === undefined) return '—'
  if (b < 1024 * 1024) return `${Math.round(b / 1024)} KB`
  return `${(b / 1024 / 1024).toFixed(1)} MB`
}

export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1)}s`
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return '—'
  const t = Date.parse(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  if (Number.isNaN(t)) return iso
  const s = Math.max(0, (Date.now() - t) / 1000)
  if (s < 60) return `${Math.round(s)}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

// --- small shared chrome ----------------------------------------------------

export function Panel({
  title, subtitle, right, children, style, bodyStyle,
}: {
  title: string
  subtitle?: ReactNode
  right?: ReactNode
  children: ReactNode
  style?: StyleInput
  bodyStyle?: StyleInput
}) {
  return (
    <section
      style={{
        ...css('background:var(--panel);border:1px solid var(--border);border-radius:10px;box-shadow:var(--shadow-sm);display:flex;flex-direction:column;min-height:0;overflow:hidden'),
        ...toStyle(style),
      }}
    >
      <header style={css('display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid var(--border);background:var(--panel-2);flex:none')}>
        <span style={css('font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--text-2)')}>{title}</span>
        {subtitle ? <span style={css('font-size:11.5px;color:var(--text-3);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{subtitle}</span> : null}
        <span style={css('flex:1')} />
        {right}
      </header>
      <div style={{ ...css('flex:1;min-height:0;overflow:auto'), ...toStyle(bodyStyle) }}>{children}</div>
    </section>
  )
}

// Empty states must say what is missing AND how to fix it — never a bare
// "no data" and never invented filler (project's no-placeholder-data rule).
export function Empty({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div style={css('padding:22px 16px;text-align:center')}>
      <div style={css('font-size:13px;font-weight:600;color:var(--text-2)')}>{title}</div>
      {hint ? <div style={css('font-size:12px;color:var(--text-3);margin-top:5px;line-height:1.55;max-width:460px;margin-left:auto;margin-right:auto')}>{hint}</div> : null}
    </div>
  )
}

export function Btn({
  children, onClick, disabled, kind = 'default', title, style,
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  kind?: 'default' | 'primary' | 'danger'
  title?: string
  style?: StyleInput
}) {
  const base = 'display:inline-flex;align-items:center;justify-content:center;gap:6px;height:28px;padding:0 11px;border-radius:7px;font-size:12.5px;font-weight:600;border:1px solid var(--border-strong);background:var(--panel)'
  const kinds: Record<string, string> = {
    default: '',
    primary: 'background:var(--primary);color:var(--on-primary);border-color:var(--primary)',
    danger: 'background:var(--panel);color:var(--danger);border-color:var(--danger-soft)',
  }
  const hovers: Record<string, string> = {
    default: 'background:var(--panel-2)',
    primary: 'background:var(--primary-2);border-color:var(--primary-2)',
    danger: 'background:var(--danger-soft)',
  }
  return (
    <Box
      as="button" type="button" onClick={onClick} disabled={disabled} title={title}
      css={`${base};${kinds[kind]}${disabled ? ';opacity:.45' : ''}`}
      style={style}
      hover={disabled ? undefined : hovers[kind]}
    >
      {children}
    </Box>
  )
}
