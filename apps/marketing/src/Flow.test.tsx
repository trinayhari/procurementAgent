// The flow section is a WAI-ARIA tablist that also advances itself every 5s.
// These cover the a11y wiring, the keyboard contract, the clock (advance,
// wrap, pause on hover / off-screen / reduced motion) and which mock each
// step shows.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react'
import Flow from './Flow'
import { reducedMotion, setInView } from './testSetup'

const tabs = () => screen.getAllByRole('tab')
const selected = () => tabs().findIndex((t) => t.getAttribute('aria-selected') === 'true')

describe('Flow tabs', () => {
  beforeEach(() => reducedMotion(true)) // freeze the clock; timer tests opt back in
  afterEach(() => { cleanup(); reducedMotion(false) })

  it('wires the tablist, tabs and panel with the right ARIA attributes', () => {
    render(<Flow />)
    expect(screen.getByRole('tablist', { name: 'Buyout steps' })).toBeTruthy()
    const all = tabs()
    expect(all).toHaveLength(4)
    expect(selected()).toBe(0)
    all.forEach((t, i) => {
      expect(t.id).toBe(`flow-tab-${i}`)
      expect(t.getAttribute('aria-controls')).toBe('flow-panel')
      expect(t.tabIndex).toBe(i === 0 ? 0 : -1)
    })
    const panel = screen.getByRole('tabpanel')
    expect(panel.id).toBe('flow-panel')
    expect(panel.getAttribute('aria-labelledby')).toBe('flow-tab-0')
  })

  it('selects a step on click, marks earlier steps done, and moves the roving tabindex', () => {
    render(<Flow />)
    fireEvent.click(tabs()[2])
    expect(selected()).toBe(2)
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe('flow-tab-2')
    expect(tabs()[0].className).toContain('flow-tab--done')
    expect(tabs()[1].className).toContain('flow-tab--done')
    expect(tabs()[2].className).not.toContain('flow-tab--done')
    expect(tabs()[3].className).not.toContain('flow-tab--done')
    expect(tabs().map((t) => t.tabIndex)).toEqual([-1, -1, 0, -1])
    expect(screen.getByText('RFQs go out, follow-ups go out, quotes come back leveled to the line.')).toBeTruthy()
  })

  it('moves with ArrowRight/ArrowLeft and wraps at both ends', () => {
    render(<Flow />)
    fireEvent.keyDown(tabs()[0], { key: 'ArrowLeft' })
    expect(selected()).toBe(3)
    expect(document.activeElement).toBe(tabs()[3])
    fireEvent.keyDown(tabs()[3], { key: 'ArrowRight' })
    expect(selected()).toBe(0)
    expect(document.activeElement).toBe(tabs()[0])
    fireEvent.keyDown(tabs()[0], { key: 'ArrowDown' })
    expect(selected()).toBe(1)
    fireEvent.keyDown(tabs()[1], { key: 'ArrowUp' })
    expect(selected()).toBe(0)
  })

  it('jumps with Home/End and ignores unrelated keys', () => {
    render(<Flow />)
    fireEvent.keyDown(tabs()[0], { key: 'End' })
    expect(selected()).toBe(3)
    fireEvent.keyDown(tabs()[3], { key: 'Home' })
    expect(selected()).toBe(0)
    fireEvent.keyDown(tabs()[0], { key: 'Enter' })
    fireEvent.keyDown(tabs()[0], { key: 'a' })
    expect(selected()).toBe(0)
  })

  it('shows the inbox stage on steps 1-3 and the chat thread on step 4', () => {
    render(<Flow />)
    // Step 1: inbox plus three ghosted system cards, no award yet.
    expect(screen.getByText('Plan set received: Riverside WTP, Rev B, 142 sheets', { selector: '.inbox__subj' })).toBeTruthy()
    expect(document.querySelectorAll('.sys')).toHaveLength(3)
    expect(document.querySelectorAll('.sys--ghost')).toHaveLength(3)
    expect(screen.queryByText('Award', { selector: '.mk__chip' })).toBeNull()
    expect(screen.getByText('The buy')).toBeTruthy()

    // Step 2: same three cards, now built (not ghosted) with "built" status.
    fireEvent.click(tabs()[1])
    expect(document.querySelectorAll('.sys--ghost')).toHaveLength(0)
    expect(document.querySelectorAll('.sys--new')).toHaveLength(3)
    expect(screen.getByText('Drafted from 142 sheets')).toBeTruthy()

    // Step 3: award card appears, statuses switch to "sourced", ticks on ok cards.
    fireEvent.click(tabs()[2])
    expect(document.querySelectorAll('.sys')).toHaveLength(4)
    expect(screen.getByText('Sourcing round · water utilities')).toBeTruthy()
    expect(screen.getByText('Split award recommended')).toBeTruthy()
    expect(document.querySelectorAll('.sys__status--ok')).toHaveLength(2)
    expect(screen.queryByText('Drafted from 142 sheets')).toBeNull()

    // Step 4: chat thread, no inbox.
    fireEvent.click(tabs()[3])
    expect(document.querySelector('.chat')).toBeTruthy()
    expect(document.querySelector('.stage')).toBeNull()
    expect(screen.getByText('Approve award')).toBeTruthy()
    expect(screen.getByText('Approved. Flag me if DI lead time slips.')).toBeTruthy()
    expect(screen.getByRole('tabpanel').textContent).toContain('PO-1042')
  })

  it('renders a full progress bar and does not auto-advance under reduced motion', () => {
    vi.useFakeTimers()
    try {
      render(<Flow />)
      const bar = tabs()[0].querySelector('.flow-tab__bar') as HTMLElement
      expect(bar.style.transform).toBe('scaleX(1)')
      act(() => { vi.advanceTimersByTime(12000) })
      expect(selected()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('Flow auto-advance', () => {
  beforeEach(() => { reducedMotion(false); vi.useFakeTimers() })
  afterEach(() => { cleanup(); vi.useRealTimers() })

  it('advances every 5s, wraps 4→1, and restarts the clock on a manual pick', () => {
    render(<Flow />)
    const bar = () => tabs()[selected()].querySelector('.flow-tab__bar') as HTMLElement
    act(() => { vi.advanceTimersByTime(2500) })
    expect(selected()).toBe(0)
    expect(parseFloat(bar().style.transform.replace(/scaleX\((.*)\)/, '$1'))).toBeCloseTo(0.5, 1)
    act(() => { vi.advanceTimersByTime(2500) })
    expect(selected()).toBe(1)
    act(() => { vi.advanceTimersByTime(5000) })
    expect(selected()).toBe(2)
    act(() => { vi.advanceTimersByTime(5000) })
    expect(selected()).toBe(3)
    expect(document.querySelector('.chat')).toBeTruthy()
    act(() => { vi.advanceTimersByTime(5000) })
    expect(selected()).toBe(0)
    expect(document.querySelector('.stage')).toBeTruthy()

    // Choosing a tab by hand restarts the clock from zero.
    act(() => { vi.advanceTimersByTime(4000) })
    fireEvent.click(tabs()[2])
    act(() => { vi.advanceTimersByTime(4000) })
    expect(selected()).toBe(2) // 4s since the click, not 8s since mount
    act(() => { vi.advanceTimersByTime(1100) })
    expect(selected()).toBe(3)
  })

  it('pauses while hovered and resumes on leave', () => {
    render(<Flow />)
    const section = document.getElementById('flow')!
    fireEvent.mouseEnter(section)
    act(() => { vi.advanceTimersByTime(20000) })
    expect(selected()).toBe(0)
    fireEvent.mouseLeave(section)
    act(() => { vi.advanceTimersByTime(5100) })
    expect(selected()).toBe(1)
  })

  it('pauses while scrolled out of view and resumes when it re-enters', () => {
    render(<Flow />)
    act(() => setInView(false))
    act(() => { vi.advanceTimersByTime(20000) })
    expect(selected()).toBe(0)
    act(() => setInView(true))
    act(() => { vi.advanceTimersByTime(5100) })
    expect(selected()).toBe(1)
  })

  it('stops when reduced motion is switched on mid-run', () => {
    render(<Flow />)
    act(() => { vi.advanceTimersByTime(5100) })
    expect(selected()).toBe(1)
    act(() => reducedMotion(true))
    act(() => { vi.advanceTimersByTime(20000) })
    expect(selected()).toBe(1)
    reducedMotion(false)
  })
})
