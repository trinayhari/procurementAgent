import { useEffect, useRef, useState } from 'react'
import { usePrefersReducedMotion } from './lib'

// The hero background: a field of faint dots on the near-black canvas, with a
// slow diagonal sweep of brightness passing through it, the only motion on
// the fold. Pure canvas, no assets. With reduced motion it renders one static
// frame; the first frame is always drawn synchronously so a hidden or paused
// tab still shows the field. The loop only runs while the canvas is on screen.

const GAP = 26

export default function HeroField() {
  const ref = useRef<HTMLCanvasElement | null>(null)
  const reduced = usePrefersReducedMotion()
  const [inView, setInView] = useState(true)
  // Animation clock, kept across loop restarts so the sweep resumes where it
  // stopped rather than jumping back to the start.
  const clock = useRef(8)

  // Stop the rAF loop once the hero has scrolled off screen; restart on return.
  // Without IntersectionObserver the canvas is treated as always in view.
  useEffect(() => {
    const canvas = ref.current
    if (!canvas || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(([e]) => setInView(e.isIntersecting), { threshold: 0 })
    io.observe(canvas)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let w = 0
    let h = 0
    let raf = 0
    let last = 0

    const draw = () => {
      const t = clock.current
      ctx.clearRect(0, 0, w, h)
      const cols = Math.ceil(w / GAP) + 1
      const rows = Math.ceil(h / GAP) + 1
      const period = 1100
      const sweep = (t * 34) % period
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const x = c * GAP
          const y = r * GAP
          // Diagonal band: distance from a line moving down-left across the field.
          let d = (x * 0.8 - y * 0.6 + 2000 - sweep) % period
          if (d < 0) d += period
          d = Math.min(d, period - d)
          const band = Math.exp(-(d * d) / (2 * 110 * 110))
          // Very slow low-frequency breathing so the static area is not flat.
          const breath = 0.5 + 0.5 * Math.sin(x * 0.006 + t * 0.25) * Math.sin(y * 0.008 - t * 0.18)
          // Fade the field out toward the bottom-left, where the headline sits.
          const fx = Math.min(1, x / (w * 0.55))
          const fy = Math.min(1, (h - y) / (h * 0.55))
          const fade = 0.35 + 0.65 * Math.max(fx, fy)
          const a = (0.045 + 0.05 * breath + 0.34 * band) * fade
          ctx.fillStyle = `rgba(245,245,245,${a.toFixed(3)})`
          ctx.fillRect(x - 0.75, y - 0.75, 1.5, 1.5)
        }
      }
    }

    const resize = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      draw()
    }

    const loop = (now: number) => {
      if (last) clock.current += Math.min(0.05, (now - last) / 1000)
      last = now
      draw()
      raf = requestAnimationFrame(loop)
    }

    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    if (!reduced && inView) raf = requestAnimationFrame(loop)

    return () => {
      ro.disconnect()
      cancelAnimationFrame(raf)
    }
  }, [reduced, inView])

  return <canvas ref={ref} className="hero__field" aria-hidden="true" />
}
