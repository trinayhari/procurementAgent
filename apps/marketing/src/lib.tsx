import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'

// Convert a CSS string ("display:flex;gap:8px") into a React style object, so
// one-off inline tweaks can be written as plain CSS next to the markup.
export function css(str?: string): CSSProperties {
  const o: Record<string, string> = {}
  if (!str) return o
  for (const part of str.split(';')) {
    const i = part.indexOf(':')
    if (i < 0) continue
    const k = part.slice(0, i).trim()
    const v = part.slice(i + 1).trim()
    if (!k) continue
    // Custom properties pass through as-is; camel-casing "--x" would mangle it.
    o[k.startsWith('--') ? k : k.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())] = v
  }
  return o as CSSProperties
}

// True when the visitor has asked for reduced motion. Every timed or looping
// animation on the page (hero field, marquee, flow auto-advance) keys off this.
export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)').matches : false,
  )
  useEffect(() => {
    const mq = matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return reduced
}

// Small inline check mark used by the flow mock and the "included" list.
export function Check({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  )
}
