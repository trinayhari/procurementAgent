import { useLayoutEffect, useRef } from 'react'
import type { CSSProperties, ElementType, ReactNode } from 'react'

// A style value may be supplied either as a CSS string ("display:flex;gap:8px")
// or as an already-built React style object.
export type StyleInput = string | CSSProperties

// Convert a CSS string ("display:flex;gap:8px") into a React style object.
// Lets us reuse the design prototype's inline-style strings nearly verbatim —
// including properties React's CSSProperties doesn't know yet, such as
// `text-box`, which the design leans on for optical heading alignment.
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

function toStyle(v?: StyleInput): CSSProperties {
  return typeof v === 'string' ? css(v) : v || {}
}

type BoxProps = {
  as?: ElementType
  css?: StyleInput
  style?: StyleInput
  children?: ReactNode
} & Record<string, unknown>

// Polymorphic element that accepts the design's inline-style strings directly.
export function Box({ as = 'div', css: base, style, children, ...rest }: BoxProps) {
  const Tag = as
  return (
    <Tag style={{ ...toStyle(base), ...toStyle(style) }} {...rest}>
      {children}
    </Tag>
  )
}

// Inline svg helper. `d` may be raw element markup (starts with "<") or bare
// path data, which is wrapped in a <path>.
export function Svg({
  d,
  size = 17,
  sw = 2,
  fill = false,
  style,
}: {
  d: string
  size?: number
  sw?: number
  fill?: boolean
  style?: CSSProperties
}) {
  const inner = d.trim().startsWith('<') ? d : `<path d="${d}" />`
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      fill={fill ? 'currentColor' : 'none'}
      stroke={fill ? 'none' : 'currentColor'}
      strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={style}
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  )
}

// Icon paths, matching apps/web/src/lib.tsx so the mock stays true to the product.
export const ICONS = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>',
  gridSm: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  folder: 'M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  supplier: '<rect x="5" y="3" width="14" height="18" rx="1.6"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M10 21v-3h4v3"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 13a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-2.87 1.2v.17a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-2.87-1.2l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 11h-.17a2 2 0 1 1 0-4h.09"/>',
  file: '<path d="M14 3v5h5"/><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/>',
  rfq: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 7 8.5 5.5L20.5 7"/>',
  quotes: '<path d="M12 3v18M6 21h12"/><path d="M5 8h14"/><path d="m5 8-2.3 5a3 3 0 0 0 5.6 0z"/><path d="m19 8 2.3 5a3 3 0 0 1-5.6 0z"/>',
  timeline: 'M4 7h9M4 12h13M4 17h6',
  pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="2.6"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/>',
  chevronRight: 'm9 6 6 6-6 6',
  chevronLeft: 'm15 18-6-6 6-6',
  check: 'm5 12 5 5L20 7',
  quote: '<circle cx="12" cy="12" r="9"/><path d="M14.5 9.3c-.5-.9-1.4-1.4-2.5-1.4-1.4 0-2.4.8-2.4 1.9 0 1 .8 1.5 2.4 1.9 1.6.4 2.5.9 2.5 2 0 1.1-1 1.9-2.5 1.9-1.1 0-2-.5-2.5-1.4M12 6.4v1.5M12 16.1v1.5"/>',
  sparkles: '<path d="M12 3l1.7 4.6L18 9l-4.3 1.4L12 15l-1.7-4.6L6 9l4.3-1.4z"/><path d="M18.5 14l.7 1.9 1.8.6-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.6z"/>',
  truck: '<path d="M3 6.5h11v9.5H3z"/><path d="M14 9.5h4l3 3.2V16h-7z"/><circle cx="7" cy="18" r="1.7"/><circle cx="17.5" cy="18" r="1.7"/>',
} as const

export const SPARKLE = 'M12 2l1.6 4.6L18 8l-4.4 1.4L12 14l-1.6-4.6L6 8l4.4-1.4z'
export const SPARKLE_SOLID = 'M12 2l1.7 4.6L18 8l-4.3 1.4L12 14l-1.7-4.6L6 8l4.3-1.4z'

// The product mock is authored at a fixed 1280px width. Scale it down to fill
// its frame and collapse the frame to the scaled height, so it behaves like a
// screenshot instead of a horizontally-scrolling app.
const MOCK_WIDTH = 1280

export function useFitToWidth() {
  const frameRef = useRef<HTMLDivElement | null>(null)
  const mockRef = useRef<HTMLDivElement | null>(null)

  useLayoutEffect(() => {
    const frame = frameRef.current
    const mock = mockRef.current
    if (!frame || !mock) return

    let lastWidth = -1
    let lastHeight = -1
    const fit = () => {
      const width = frame.clientWidth
      const height = mock.offsetHeight
      // A hidden ancestor measures 0 wide; scaling to 0 there would collapse the
      // frame, and it would not necessarily be re-measured on the way back.
      if (!width) return
      // fit() writes the frame's height, which the observer sees as a resize.
      // Bailing when nothing actually moved is what terminates that loop — do
      // not defer to rAF instead, it never runs while the page is hidden and the
      // mock would stay stuck at whatever scale it last had.
      if (width === lastWidth && height === lastHeight) return
      lastWidth = width
      lastHeight = height
      const k = Math.min(1, width / MOCK_WIDTH)
      mock.style.transform = `scale(${k})`
      frame.style.height = `${Math.round(height * k)}px`
    }

    fit()
    // Watch the frame for container-driven width changes and the mock for height
    // changes. ResizeObserver is not enough on its own: it only delivers during
    // the rendering steps, which a hidden document skips entirely — hence the
    // resize/visibility listeners and the fonts.ready re-measure alongside it.
    const ro = new ResizeObserver(fit)
    ro.observe(frame)
    ro.observe(mock)
    addEventListener('resize', fit)
    addEventListener('visibilitychange', fit)
    document.fonts?.ready.then(fit)

    return () => {
      ro.disconnect()
      removeEventListener('resize', fit)
      removeEventListener('visibilitychange', fit)
    }
  }, [])

  return [frameRef, mockRef] as const
}
