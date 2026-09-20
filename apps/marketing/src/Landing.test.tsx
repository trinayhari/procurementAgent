// Page-level behaviour: the CTAs only become links once VITE_DEMO_URL is
// configured, the nav goes solid on scroll, and the "Who it's for" accordion
// keeps exactly one panel open (or none).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react'
import { reducedMotion } from './testSetup'

const CTA_LABELS = ['Talk to us', 'Request a buyout', 'Start a conversation ↗']

async function loadLanding() {
  vi.resetModules()
  const mod = await import('./Landing')
  return mod.default
}

describe('Landing', () => {
  beforeEach(() => reducedMotion(true))
  afterEach(() => { cleanup(); vi.unstubAllEnvs(); reducedMotion(false) })

  it('renders the CTAs as inert buttons when VITE_DEMO_URL is unset', async () => {
    vi.stubEnv('VITE_DEMO_URL', '')
    const Landing = await loadLanding()
    render(<Landing />)
    for (const label of CTA_LABELS) {
      const el = screen.getByText(label)
      expect(el.tagName).toBe('BUTTON')
      expect(el.getAttribute('type')).toBe('button')
    }
    expect(screen.queryByRole('link', { name: 'Request a buyout' })).toBeNull()
  })

  it('renders the CTAs as links to VITE_DEMO_URL when it is set', async () => {
    vi.stubEnv('VITE_DEMO_URL', 'https://cal.com/proq/intro')
    const Landing = await loadLanding()
    render(<Landing />)
    for (const label of CTA_LABELS) {
      const el = screen.getByRole('link', { name: label })
      expect(el.getAttribute('href')).toBe('https://cal.com/proq/intro')
      expect(el.className).toContain('btn')
    }
    expect(screen.getByRole('link', { name: 'Talk to us' }).className).toContain('btn--ghost')
    expect(screen.getByRole('link', { name: 'Request a buyout' }).className).toContain('btn--lg')
  })

  it('composes the sections in order and toggles the nav solid past 24px of scroll', async () => {
    const Landing = await loadLanding()
    render(<Landing />)
    const ids = Array.from(document.querySelectorAll('section[id], #flow')).map((s) => s.id)
    expect(ids).toEqual(['pain', 'what', 'flow', 'included', 'who'])
    expect(document.querySelectorAll('.stat')).toHaveLength(6)
    expect(document.querySelectorAll('.inc')).toHaveLength(8)
    expect(screen.getAllByText('Human approves')).toHaveLength(3)
    expect(document.querySelectorAll('.value')).toHaveLength(4)
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(nav.className).toBe('nav')
    act(() => {
      Object.defineProperty(window, 'scrollY', { value: 80, configurable: true })
      window.dispatchEvent(new Event('scroll'))
    })
    expect(nav.className).toBe('nav nav--solid')
    act(() => {
      Object.defineProperty(window, 'scrollY', { value: 0, configurable: true })
      window.dispatchEvent(new Event('scroll'))
    })
    expect(nav.className).toBe('nav')
  })

  it('accordion opens the first item by default, swaps on click, and can close entirely', async () => {
    const Landing = await loadLanding()
    render(<Landing />)
    const btns = ['Commercial & institutional GCs', 'Self-perform & civil', 'MEP long-lead']
      .map((n) => screen.getByRole('button', { name: n }))
    const panels = btns.map((b) => document.getElementById(b.getAttribute('aria-controls')!)!)
    expect(btns.map((b) => b.getAttribute('aria-expanded'))).toEqual(['true', 'false', 'false'])
    expect(panels.map((p) => p.hidden)).toEqual([false, true, true])
    expect(panels[0].getAttribute('aria-labelledby')).toBe(btns[0].id)

    fireEvent.click(btns[2])
    expect(btns.map((b) => b.getAttribute('aria-expanded'))).toEqual(['false', 'false', 'true'])
    expect(panels.map((p) => p.hidden)).toEqual([true, true, false])
    expect(panels[2].textContent).toContain('Switchgear, RTUs, generators')

    fireEvent.click(btns[2]) // clicking the open one closes it; nothing is open
    expect(btns.map((b) => b.getAttribute('aria-expanded'))).toEqual(['false', 'false', 'false'])
    expect(panels.every((p) => p.hidden)).toBe(true)
  })
})
