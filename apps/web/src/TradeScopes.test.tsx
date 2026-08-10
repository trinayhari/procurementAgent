// Subcontractor trade scopes: the Documents tab lists them in their own card,
// and the Suppliers tab surfaces each as a selectable trade chip whose panel is
// the scope-of-work editor (not a BOM list). Drives the real <App /> against a
// mocked fetch, mirroring App.test.tsx.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import App from './App'

const USER = { id: 'u-pm', email: 'pm@acmebuild.com', name: 'PM', company: 'Acme Build Co.', ccEmail: null }

const PROJECT = {
  id: 'p-1', name: 'Riverside Yard', loc: 'Austin, TX', stage: 'Plans Review',
  stageTone: 'gray', value: '$1.0M', progress: 0, suppliers: 0, rfqs: 0, quotes: 0,
  risk: 'Low', riskTone: 'success', barColor: 'var(--primary)',
}

const TRADE_DOC = {
  id: 'trade-1', name: 'Concrete flatwork', type: 'Trade Scope', date: 'Aug 09, 2026',
  status: 'Draft', statusTone: 'gray', items: '—', pages: 0, processing: false,
  hasFile: false, planType: 'trade_scope', summary: 'Pour 12,400 SF of sidewalk.',
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input instanceof Request ? input.url : input)
  const path = url.replace(/^https?:\/\/[^/]+/, '')

  if (path === '/api/auth/login') return json({ accessToken: 'tok', user: USER })
  if (path === '/api/auth/me') return json(USER)
  if (path === '/api/dashboard') return json({ metrics: [], activity: [] })
  if (path === '/api/projects') return json([PROJECT])
  if (path === '/api/suppliers') return json([])
  if (path === '/api/documents/plan-types') return json([])
  if (path.endsWith('/documents')) return json([TRADE_DOC])
  if (path.endsWith('/trades')) return json([{ id: TRADE_DOC.id, name: TRADE_DOC.name, scope: TRADE_DOC.summary }])
  if (path.endsWith('/boms')) return json([])
  if (path.includes('/suppliers/found')) return json({ status: 'idle', mocked: false, radiusMi: 0, package: '', error: null, tiers: [] })
  if (path.includes('/timeline')) return json({ milestones: [], gantt: [], ganttCols: [] })
  if (path.includes('/comparison')) return json({ suppliers: [], rows: [], recommendation: '', reasons: [], savings: '', savingsNote: '' })
  if (/^\/api\/projects\/[^/]+$/.test(path)) return json({ overviewCards: [], packages: [], activity: [] })
  if (path.includes('/line-items')) return json([])
  return json([])
})

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', window.location.pathname)
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function openProject() {
  render(<App />)
  await screen.findByPlaceholderText('you@company.com')
  fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: USER.email } })
  fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  fireEvent.click(await screen.findByText('Riverside Yard'))
  await waitFor(() => expect(window.location.hash).toBe('#/project/p-1/overview'))
}

describe('subcontractor trade scopes', () => {
  it('lists trade scopes in their own Documents-tab card with a scope editor', async () => {
    await openProject()
    fireEvent.click(screen.getByRole('button', { name: /Documents/ }))

    // The card and its row render from planType === 'trade_scope'.
    await screen.findByText('Subcontractor trades')
    // It's the only document, so it's auto-selected: the name shows in the card
    // row AND the editor header.
    expect(await screen.findAllByText('Concrete flatwork')).toHaveLength(2)
    expect(screen.getByText('Scope written')).toBeTruthy()

    // The selected trade shows the scope-of-work editor (not a PDF preview).
    await screen.findByText('Trade scope')
    const editor = screen.getByDisplayValue('Pour 12,400 SF of sidewalk.')
    expect(editor.tagName).toBe('TEXTAREA')
  })

  it('offers the trade as a chip in supplier search with the scope panel', async () => {
    await openProject()
    fireEvent.click(screen.getByRole('button', { name: /Supplier Search/ }))

    // The trade chip loads from GET /trades; clicking it swaps the BOM panel
    // for the scope editor and relabels the actions for a sub bid.
    const chip = await screen.findByRole('button', { name: /Concrete flatwork/ })
    fireEvent.click(chip)
    await screen.findByText(/Scope of work · Concrete flatwork/)
    expect(screen.getByDisplayValue('Pour 12,400 SF of sidewalk.')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Search subcontractors/ })).toBeTruthy()
  })
})
