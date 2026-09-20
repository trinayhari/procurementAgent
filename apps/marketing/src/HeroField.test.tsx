// The hero canvas must always paint one frame synchronously, keep animating
// with rAF when motion is allowed, and stop at that frame under reduced
// motion (and on unmount).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import HeroField from './HeroField'
import { canvasCtx, reducedMotion } from './testSetup'

describe('HeroField', () => {
  let raf: ReturnType<typeof vi.spyOn>
  let caf: ReturnType<typeof vi.spyOn>
  beforeEach(() => {
    canvasCtx.clearRect.mockClear()
    canvasCtx.fillRect.mockClear()
    raf = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 7)
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

  it('renders a single static frame under reduced motion', () => {
    reducedMotion(true)
    render(<HeroField />)
    expect(canvasCtx.clearRect).toHaveBeenCalledTimes(1)
    expect(raf).not.toHaveBeenCalled()
  })
})
