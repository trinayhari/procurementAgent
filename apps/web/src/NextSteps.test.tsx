// The Overview checklist is computed from the project's real state — it must
// point at exactly one current step and never claim progress that hasn't
// happened. Pure-function cases plus one render on an empty project.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { computeSteps } from './App'
import { makeFetch, openProject, resetDom, PROJECT } from './testUtils'

const nav = { documents: vi.fn(), suppliers: vi.fn(), rfqs: vi.fn(), quotes: vi.fn() }
const plan = (over: Partial<{ reviewed: boolean; processing: boolean; status: string; items: string }> = {}) =>
  ({ planType: 'site_plan', hasFile: true, reviewed: false, processing: false, status: 'Analyzed', items: '12', ...over })

const states = (steps: ReturnType<typeof computeSteps>) => steps.map((s) => s.state)

describe('computeSteps', () => {
  it('starts a brand-new project at "upload"', () => {
    const steps = computeSteps({ docs: [], rfqs: [], quotes: 0, decisions: 0, nav })
    expect(states(steps)).toEqual(['current', 'todo', 'todo', 'todo', 'todo'])
    expect(steps[0].cta).toBe('Go to Documents')
  })

  it('moves to review once a plan is analyzed, and to sourcing once confirmed', () => {
    let steps = computeSteps({ docs: [plan()], rfqs: [], quotes: 0, decisions: 0, nav })
    expect(states(steps)).toEqual(['done', 'current', 'todo', 'todo', 'todo'])
    expect(steps[1].detail).toContain('1 document awaiting your review')
    expect(steps[1].cta).toBe('Review BOM')

    steps = computeSteps({ docs: [plan({ reviewed: true })], rfqs: [], quotes: 0, decisions: 0, nav })
    expect(states(steps)).toEqual(['done', 'done', 'current', 'todo', 'todo'])
    expect(steps[2].cta).toBe('Find suppliers')
  })

  it('points at unsent drafts, then at collecting quotes, then at awarding', () => {
    let steps = computeSteps({ docs: [plan({ reviewed: true })], rfqs: [{ status: 'Draft' }], quotes: 0, decisions: 0, nav })
    expect(steps[2].state).toBe('current')
    expect(steps[2].cta).toBe('Open drafts')
    steps[2].go!()
    expect(nav.rfqs).toHaveBeenCalled()

    steps = computeSteps({ docs: [plan({ reviewed: true })], rfqs: [{ status: 'Awaiting' }], quotes: 0, decisions: 0, nav })
    expect(states(steps)).toEqual(['done', 'done', 'done', 'current', 'todo'])

    steps = computeSteps({ docs: [plan({ reviewed: true })], rfqs: [{ status: 'Quoted' }], quotes: 2, decisions: 0, nav })
    expect(states(steps)).toEqual(['done', 'done', 'done', 'done', 'current'])
    expect(steps[4].cta).toBe('Compare quotes')

    steps = computeSteps({ docs: [plan({ reviewed: true })], rfqs: [{ status: 'Quoted' }], quotes: 2, decisions: 1, nav })
    expect(states(steps)).toEqual(['done', 'done', 'done', 'done', 'done'])
  })

  it('reports failed and in-progress extractions honestly', () => {
    const steps = computeSteps({ docs: [plan({ status: 'Failed', items: '—' }), plan({ processing: true, status: 'Processing', items: '—' })], rfqs: [], quotes: 0, decisions: 0, nav })
    expect(steps[0].detail).toContain('1 still analyzing')
    expect(steps[0].detail).toContain('1 failed')
    expect(steps[1].state).toBe('current')
    expect(steps[1].cta).toBeUndefined() // nothing reviewable yet
  })
})

describe('overview checklist', () => {
  beforeEach(() => resetDom())
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('renders on an empty project and routes to Documents', async () => {
    vi.stubGlobal('fetch', makeFetch(() => undefined))
    await openProject()
    await screen.findByText('Where this project stands')
    expect(screen.getByText('0/5')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Go to Documents/ }))
    await waitFor(() => expect(window.location.hash).toBe(`#/project/${PROJECT.id}/documents`))
  })
})
