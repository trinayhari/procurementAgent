// The hero canvas must always paint one frame synchronously, keep animating
// with rAF while motion is allowed and the canvas is on screen, and stop at
// that frame under reduced motion, off screen, and on unmount.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, act } from '@testing-library/react'
import HeroField from './HeroField'
import { canvasCtx, reducedMotion, setInView } from './testSetup'

describe('HeroField', () => {
  let raf: ReturnType<typeof vi.spyOn>
  let caf: ReturnType<typeof vi.spyOn>
  let frame: FrameRequestCallback | null
  beforeEach(() => {
    canvasCtx.clearRect.mockClear()
    canvasCtx.fillRect.mockClear()
    frame = null
    raf = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => { frame = cb; return 7 })
    caf = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})
  })
  afterEach(() => { cleanup(); raf.mockRestore(); caf.mockRestore(); reducedMotion(false) })

  it('draws the first frame synchronously and schedules the loop', () => {
    const { container, unmount } = render(<HeroField />)
    const canvas = container.querySelector('canvas')!
    expect(canvas.getAttribute('aria-hidden')).toBe('true')
    expect(canvasCtx.clearRect).toHaveBeenCalledTimes(1)
    expect(canvasCtx.fillRect).toHaveBeenCalled()
    expect(raf).toHaveBeenCalledTimes(1)
    unmount()
    expect(caf).toHaveBeenCalledWith(7)
  })

  it('repaints on every animation frame and reschedules itself', () => {
    render(<HeroField />)
    expect(frame).not.toBeNull()
    act(() => { frame!(16) })
    expect(canvasCtx.clearRect).toHaveBeenCalledTimes(2)
    expect(raf).toHaveBeenCalledTimes(2)
    act(() => { frame!(32) })
    expect(canvasCtx.clearRect).toHaveBeenCalledTimes(3)
    expect(raf).toHaveBeenCalledTimes(3)
  })

  it('cancels the loop while scrolled off screen and restarts it on return', () => {
    render(<HeroField />)
    expect(raf).toHaveBeenCalledTimes(1)
    act(() => setInView(false))
    expect(caf).toHaveBeenCalledWith(7)
    expect(raf).toHaveBeenCalledTimes(1) // no new frame scheduled while hidden
    act(() => setInView(true))
    expect(raf).toHaveBeenCalledTimes(2)
  })

  it('renders a single static frame under reduced motion', () => {
    reducedMotion(true)
    render(<HeroField />)
    expect(canvasCtx.clearRect).toHaveBeenCalledTimes(1)
    expect(raf).not.toHaveBeenCalled()
  })
})
