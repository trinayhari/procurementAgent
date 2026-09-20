// The flow section is a WAI-ARIA tablist that also advances itself every 5s.
// These cover the a11y wiring, the keyboard contract, the clock (advance,
// wrap, pause on hover / focus / off-screen / reduced motion, stop for good
// after a manual pick), the connector lines and which mock each step shows.
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

  it('draws one connector line per visible system card once the stage is wide enough', () => {
    // happy-dom has no layout; give every element a plausible box so the
    // stage passes its 700px width gate and the connector geometry resolves.
    const proto = HTMLElement.prototype
    const keys = ['offsetWidth', 'offsetHeight', 'offsetLeft', 'offsetTop'] as const
    const saved = Object.fromEntries(keys.map((k) => [k, Object.getOwnPropertyDescriptor(proto, k)]))
    Object.defineProperty(proto, 'offsetWidth', { configurable: true, get: () => 1000 })
    Object.defineProperty(proto, 'offsetHeight', { configurable: true, get: () => 160 })
    Object.defineProperty(proto, 'offsetLeft', { configurable: true, get: () => 40 })
    Object.defineProperty(proto, 'offsetTop', { configurable: true, get: () => 30 })
    try {
      render(<Flow />)
      const paths = () => document.querySelectorAll('.stage__lines path')
      expect(paths()).toHaveLength(0) // step 1: nothing is connected yet
      fireEvent.click(tabs()[1])
      expect(paths()).toHaveLength(3)
      fireEvent.click(tabs()[2])
      expect(paths()).toHaveLength(4)
      expect(document.querySelectorAll('.stage__lines circle.on').length).toBeGreaterThan(0)
      fireEvent.click(tabs()[0])
      expect(paths()).toHaveLength(0)
    } finally {
      for (const k of keys) {
        const d = saved[k]
        if (d) Object.defineProperty(proto, k, d)
        else delete (proto as unknown as Record<string, unknown>)[k]
      }
    }
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

  it('advances every 5s, wraps 4→1, and stops for good after a manual pick', () => {
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

    // Choosing a tab by hand stops the clock: the carousel never moves under
    // someone who has interacted with it.
    act(() => { vi.advanceTimersByTime(4000) })
    fireEvent.click(tabs()[2])
    expect(selected()).toBe(2)
    expect((tabs()[2].querySelector('.flow-tab__bar') as HTMLElement).style.transform).toBe('scaleX(0)')
    act(() => { vi.advanceTimersByTime(30000) })
    expect(selected()).toBe(2)
    const section = document.getElementById('flow')!
    fireEvent.mouseEnter(section)
    fireEvent.mouseLeave(section)
    act(() => { vi.advanceTimersByTime(30000) })
    expect(selected()).toBe(2)
  })

  it('stops for good after a keyboard pick as well', () => {
    render(<Flow />)
    fireEvent.keyDown(tabs()[0], { key: 'ArrowRight' })
    expect(selected()).toBe(1)
    fireEvent.blur(tabs()[1], { relatedTarget: document.body })
    act(() => { vi.advanceTimersByTime(30000) })
    expect(selected()).toBe(1)
  })

  it('pauses while a tab has keyboard focus and resumes once focus leaves the section', () => {
    render(<Flow />)
    fireEvent.focus(tabs()[0])
    act(() => { vi.advanceTimersByTime(20000) })
    expect(selected()).toBe(0)
    // Focus moving between tabs inside the section is not a leave.
    fireEvent.blur(tabs()[0], { relatedTarget: tabs()[1] })
    fireEvent.focus(tabs()[1])
    act(() => { vi.advanceTimersByTime(20000) })
    expect(selected()).toBe(0)
    fireEvent.blur(tabs()[1], { relatedTarget: document.body })
    act(() => { vi.advanceTimersByTime(5100) })
    expect(selected()).toBe(1)
  })

  it('keeps its progress across a hover pause rather than restarting the step', () => {
    render(<Flow />)
    const section = document.getElementById('flow')!
    act(() => { vi.advanceTimersByTime(2500) })
    fireEvent.mouseEnter(section)
    act(() => { vi.advanceTimersByTime(20000) })
    expect(selected()).toBe(0)
    fireEvent.mouseLeave(section)
    act(() => { vi.advanceTimersByTime(2600) })
    expect(selected()).toBe(1) // 2.5s before the pause plus 2.6s after, not a fresh 5s
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
