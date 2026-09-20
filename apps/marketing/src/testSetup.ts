// happy-dom lacks a few browser APIs the landing page leans on. Stub them
// once here so each suite can override behaviour (reduced motion, viewport
// visibility) without re-declaring the shape.
import { vi } from 'vitest'

export type MediaQueryStub = MediaQueryList & { set: (matches: boolean) => void }

// matchMedia: a controllable list. `reducedMotion(true)` flips the query and
// notifies listeners the way a real OS toggle would.
const listeners = new Set<() => void>()
let reduced = false
export const reducedMotion = (on: boolean) => {
  reduced = on
  listeners.forEach((fn) => fn())
}
window.matchMedia = vi.fn((query: string) => {
  const mq = {
    get matches() { return query.includes('reduced-motion') ? reduced : false },
    media: query,
    onchange: null,
    addEventListener: (_: string, fn: () => void) => { listeners.add(fn) },
    removeEventListener: (_: string, fn: () => void) => { listeners.delete(fn) },
    addListener: (fn: () => void) => { listeners.add(fn) },
    removeListener: (fn: () => void) => { listeners.delete(fn) },
    dispatchEvent: () => true,
  }
  return mq as unknown as MediaQueryList
})

// IntersectionObserver: records every instance so a test can drive visibility.
type IOCallback = (entries: IntersectionObserverEntry[]) => void
export const intersectionObservers: { cb: IOCallback; el: Element | null }[] = []
export const setInView = (isIntersecting: boolean) => {
  intersectionObservers.forEach((o) => o.cb([{ isIntersecting, target: o.el } as unknown as IntersectionObserverEntry]))
}
class IO {
  el: Element | null = null
  constructor(private cb: IOCallback) { intersectionObservers.push({ cb, el: null }) }
  observe(el: Element) {
    const rec = intersectionObservers.find((o) => o.cb === this.cb)
    if (rec) rec.el = el
  }
  unobserve() {}
  disconnect() {
    const i = intersectionObservers.findIndex((o) => o.cb === this.cb)
    if (i >= 0) intersectionObservers.splice(i, 1)
  }
  takeRecords() { return [] }
}
window.IntersectionObserver = IO as unknown as typeof IntersectionObserver

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = RO as unknown as typeof ResizeObserver

// Canvas: happy-dom has no 2D context. Hand back a recording stub so the
// hero field's draw loop can run and its calls can be asserted.
export const canvasCtx = {
  clearRect: vi.fn(),
  fillRect: vi.fn(),
  setTransform: vi.fn(),
  fillStyle: '',
}
HTMLCanvasElement.prototype.getContext = vi.fn(() => canvasCtx) as unknown as typeof HTMLCanvasElement.prototype.getContext
