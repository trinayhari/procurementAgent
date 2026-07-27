import { useState } from 'react'
import type { CSSProperties, ElementType, ReactNode } from 'react'

// A style value may be supplied either as a CSS string ("display:flex;gap:8px")
// or as an already-built React style object.
export type StyleInput = string | CSSProperties

// Convert a CSS string ("display:flex;gap:8px") into a React style object.
// Lets us reuse the design prototype's inline-style strings nearly verbatim.
export function css(str?: string): CSSProperties {
  const o: Record<string, string> = {}
  if (!str) return o
  for (const part of str.split(';')) {
    const i = part.indexOf(':')
    if (i < 0) continue
    const k = part.slice(0, i).trim()
    const v = part.slice(i + 1).trim()
    if (!k) continue
    // Custom properties are passed through as-is; camel-casing "--panel-2"
    // would mangle it into "-Panel-2" and the declaration would be dropped.
    o[k.startsWith('--') ? k : k.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())] = v
  }
  return o as CSSProperties
}

// Polymorphic element with optional hover styles (replaces the design's `style-hover`).
// `css`/`hover` accept either a CSS string or an already-built style object.
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

export function Box({ as = 'div', css: base, hover, style, children, ...rest }: BoxProps) {
  const [h, setH] = useState(false)
  const merged: CSSProperties = { ...toStyle(base), ...toStyle(style), ...(h && hover ? toStyle(hover) : {}) }
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

// --- Icons (stroke/fill paths copied from the design) ---
export const ICONS: Record<string, string> = {
  quote: '<circle cx="12" cy="12" r="9"/><path d="M14.5 9.3c-.5-.9-1.4-1.4-2.5-1.4-1.4 0-2.4.8-2.4 1.9 0 1 .8 1.5 2.4 1.9 1.6.4 2.5.9 2.5 2 0 1.1-1 1.9-2.5 1.9-1.1 0-2-.5-2.5-1.4M12 6.4v1.5M12 16.1v1.5"/>',
  rfq: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 7 8.5 5.5L20.5 7"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.4 2.4L15.5 9.5"/>',
  truck: '<path d="M3 6.5h11v9.5H3z"/><path d="M14 9.5h4l3 3.2V16h-7z"/><circle cx="7" cy="18" r="1.7"/><circle cx="17.5" cy="18" r="1.7"/>',
  supplier: '<rect x="5" y="3" width="14" height="18" rx="1.6"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M10 21v-3h4v3"/>',
  sparkles: '<path d="M12 3l1.7 4.6L18 9l-4.3 1.4L12 15l-1.7-4.6L6 9l4.3-1.4z"/><path d="M18.5 14l.7 1.9 1.8.6-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.6z"/>',
  file: '<path d="M14 3v5h5"/><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/>',
  alert: '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4M12 17.2v.3"/>',
  calendar: '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M4 9.5h16M8.5 3v3.5M15.5 3v3.5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 1.8"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-.5 4"/><path d="M20 4v5h-5"/>',
}
export function ic(n: string): { __html: string } {
  return { __html: ICONS[n] || '' }
}

// Renders an inline svg icon from the ICONS map (used by chip/activity rows).
export function DcIcon({
  name,
  size = 15,
  stroke = true,
  fill = false,
}: {
  name: string
  size?: number
  stroke?: boolean
  fill?: boolean
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={fill ? 'currentColor' : 'none'}
      stroke={stroke && !fill ? 'currentColor' : 'none'}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      dangerouslySetInnerHTML={ic(name)}
    />
  )
}

// --- Style token helpers (from the design's DCLogic methods) ---
export type Tone = 'blue' | 'violet' | 'gray' | 'success' | 'warn' | 'danger' | 'ai'

export function tone(t: string): { bg: string; fg: string } {
  const M: Record<string, [string, string]> = {
    blue: ['var(--primary-soft)', 'var(--primary)'],
    violet: ['var(--violet-soft)', 'var(--violet)'],
    gray: ['var(--panel-3)', 'var(--text-2)'],
    success: ['var(--success-soft)', 'var(--success)'],
    warn: ['var(--warn-soft)', 'var(--warn)'],
    danger: ['var(--danger-soft)', 'var(--danger)'],
    ai: ['var(--primary-soft)', 'var(--primary)'],
  }
  const [bg, fg] = M[t] || M.gray
  return { bg, fg }
}
export function badge(t: string, opts?: CSSProperties): CSSProperties {
  const { bg, fg } = tone(t)
  return {
    display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 9px',
    borderRadius: 999, fontSize: 12, fontWeight: 600, background: bg, color: fg,
    whiteSpace: 'nowrap', lineHeight: 1.3, ...(opts || {}),
  }
}
export function chip(t: string): CSSProperties {
  const { bg, fg } = tone(t)
  return {
    width: 30, height: 30, borderRadius: 9, flex: 'none', display: 'flex',
    alignItems: 'center', justifyContent: 'center', background: bg, color: fg,
  }
}
export function bar(pct: number | string, color?: string): CSSProperties {
  return { width: pct + '%', height: '100%', borderRadius: 999, background: color || 'var(--primary)' }
}
// Logo badge style helper (`lb` in the design).
export function lb(bg: string, size?: number): CSSProperties {
  return {
    width: size || 38, height: size || 38, borderRadius: size && size < 32 ? 8 : 10,
    background: bg, color: '#fff', display: 'flex', alignItems: 'center',
    justifyContent: 'center', fontWeight: 700, fontSize: size && size <= 34 ? 11 : 13,
    flex: 'none', letterSpacing: '-.02em',
  }
}
