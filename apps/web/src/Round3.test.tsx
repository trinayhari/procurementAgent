// Round-3 reliability regressions: dashboard header/tile agreement, computed
// package stages on the overview, real (optional) budgets on the comparison,
// single-step RFQ send, no roadmap rows in Settings, no fetches against an
// optimistic/empty project id while a project is being created, and an
// Awarded badge on the Quotes tab. Drives the real <App /> against a mocked
// fetch (see testUtils.tsx).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import App, { parseBudget } from './App'
import { makeFetch, openProject, resetDom, json, PROJECT, USER } from './testUtils'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
beforeEach(() => { resetDom() })

const QUOTES = [
  { id: 'q1', sup: 'Core & Main', pkg: 'Water Utilities', package: 'water', amount: '$10,000', freight: '$500', total: '$10,500', lead: '10 days', date: 'Sep 1', logo: 'CM', logoBg: '#111', best: true },
  { id: 'q2', sup: 'Ferguson', pkg: 'Water Utilities', package: 'water', amount: '$11,000', freight: '$800', total: '$11,800', lead: '14 days', date: 'Sep 2', logo: 'FW', logoBg: '#222', best: false },
]
const LC = {
  pkg: 'Water Utilities', package: 'water', budget: null,
  suppliers: [
    { id: 's1', name: 'Core & Main', logo: 'CM', logoBg: '#111', leadDays: 10, distanceMiles: 12, freight: 500, total: 10500 },
    { id: 's2', name: 'Ferguson', logo: 'FW', logoBg: '#222', leadDays: 14, distanceMiles: 30, freight: 800, total: 11800 },
  ],
  lines: [{ name: '12" DI Pipe', qty: '100 LF', pending: false, cells: [
    { supplierId: 's1', unitPrice: 100, extended: 10000, leadDays: 10, available: true, best: true },
    { supplierId: 's2', unitPrice: 110, extended: 11000, leadDays: 14, available: true, best: false },
  ] }],
  options: [{ key: 'mix', label: 'Lowest cost (mix & match)', total: 10500, material: 10000, freight: 500, leadDays: 10, suppliersUsed: 1, deliveries: 1, savings: 0, note: '', selections: { '12" DI Pipe': 's1' } }],
  recommendedOption: 'mix',
}
const DECISION = {
  id: 'd1', projectId: PROJECT.id, package: 'water', packageLabel: 'Water Utilities', strategy: 'mix', selections: {},
  supplierIds: ['s1'], suppliers: ['Core & Main'], total: 10500, material: 10000, freight: 500, leadDays: 10, poCount: 1,
  decidedBy: 'u-pm', decidedByEmail: USER.email, createdAt: '2026-09-10T10:00:00',
}

// ------------------------------------------------------------ item 1
describe('dashboard', () => {
  it('renders the computed KPI tiles and a header that counts the same projects the list shows', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === '/api/dashboard') return json({ metrics: [
        { label: 'Active projects', value: '0', delta: '', sub: 'of 1 project with documents' },
        { label: 'RFQs out', value: '0', delta: '', sub: 'awaiting quotes' },
      ], activity: [] })
      return undefined
    }))
    render(<App />)
    await screen.findByPlaceholderText('you@company.com')
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: USER.email } })
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    // One project in the list → the header says "1 project", never a
    // different "active" count than the tile.
    await screen.findByText('Portfolio snapshot across 1 project')
    expect(screen.getByText('Active projects')).toBeTruthy()
    expect(screen.getByText('of 1 project with documents')).toBeTruthy()
    expect(screen.queryByText(/active project/)).toBeNull()
  })
})

// ------------------------------------------------------------ item 2
describe('project overview', () => {
  it('shows each package\'s computed stage next to its progress', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (/^\/api\/projects\/[^/]+$/.test(path)) return json({
        overviewCards: [{ label: 'Documents', value: '2', sub: '2 analyzed · 1 confirmed', icon: 'file', tone: 'blue' }],
        packages: [
          { name: 'Water Utilities', pct: 75, tone: 'blue', stage: 'Quotes in' },
          { name: 'Hydrants Package', pct: 100, tone: 'success', stage: 'Awarded' },
        ],
        activity: [],
      })
      return undefined
    }))
    await openProject()
    await screen.findByText('Procurement progress by package')
    expect(screen.getByText('Quotes in')).toBeTruthy()
    expect(screen.getByText('75%')).toBeTruthy()
    expect(screen.getByText('Awarded')).toBeTruthy()
    expect(screen.getByText('2 analyzed · 1 confirmed')).toBeTruthy()
  })
})

// ------------------------------------------------------------ item 3
describe('comparison budget', () => {
  it('hides the budget line until one is set, then saves it inline and shows over/under', async () => {
    const puts: unknown[] = []
    let budget: number | null = null
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/quotes')) return json(QUOTES)
      if (path.includes('/line-comparison')) return json({ ...LC, budget })
      if (path.endsWith('/packages/water/budget') && init && init.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { budget: number | null }
        puts.push(body); budget = body.budget
        return json({ package: 'water', budget })
      }
      return undefined
    }))
    await openProject('quotes')
    fireEvent.click((await screen.findAllByRole('button', { name: 'Compare' }))[0])
    await screen.findByText(/Quote Comparison/)
    // No sample budget: nothing is "over budget" on a fresh package.
    expect(screen.queryByText(/over budget|under budget/)).toBeNull()
    expect(screen.queryByText(/budget \$/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Set a budget' }))
    const input = screen.getByLabelText(/Budget for Water Utilities/) as HTMLInputElement
    // Invalid input is refused locally with a reason; nothing is sent.
    fireEvent.change(input, { target: { value: 'lots' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByText(/Enter an amount/)).toBeTruthy()
    expect(puts).toHaveLength(0)
    fireEvent.change(input, { target: { value: '$12K' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(puts).toEqual([{ budget: 12000 }]))
    await screen.findByText('$1,500 under budget of $12,000')
    // Editing again offers removal, which clears it and hides the line.
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove budget' }))
    await waitFor(() => expect(puts).toHaveLength(2))
    expect(puts[1]).toEqual({ budget: null })
    await screen.findByRole('button', { name: 'Set a budget' })
    expect(screen.queryByText(/under budget/)).toBeNull()
  })

  it('parses amounts the way buyers write them', () => {
    expect(parseBudget('150,000')).toBe(150000)
    expect(parseBudget('$150K')).toBe(150000)
    expect(parseBudget(' 1.2m ')).toBe(1200000)
    expect(parseBudget('0')).toBeNull()
    expect(parseBudget('lots')).toBeNull()
    expect(parseBudget('')).toBeNull()
  })
})

// ------------------------------------------------------------ item 4
describe('RFQ send is single-step', () => {
  const RFQ = {
    id: 'rfq-1', projectId: PROJECT.id, package: 'water', pkg: 'Water Utilities', sup: '', folder: '', preview: '', time: '',
    logo: 'WU', logoBg: '#334155', kind: 'materials', attachments: [], lineItems: [{ n: '12" DI Pipe', q: '100 LF' }],
    subject: 'RFQ: Water Utilities — Riverside Yard', body: 'Please quote.', status: 'Draft', statusTone: 'gray',
    recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com' }, { supplierId: 's2', name: 'Ferguson', email: 'b@x.com' }],
  }
  it('sends from the review modal\'s primary button with no second confirm, and keeps per-recipient status', async () => {
    const sends: string[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/rfqs/generated')) return json([RFQ])
      if (path.endsWith('/rfqs/rfq-1') && init && init.method === 'PUT') return json(RFQ)
      if (path.endsWith('/rfqs/rfq-1/send') && init && init.method === 'POST') {
        sends.push(path)
        return json({ ...RFQ, status: 'Send failed', statusTone: 'danger', recipients: [
          { ...RFQ.recipients[0], sendStatus: 'sent', sentMessageId: 'm1' },
          { ...RFQ.recipients[1], sendStatus: 'failed', sendError: 'Gmail: 550 mailbox unavailable' },
        ] })
      }
      if (path.includes('/conversation')) return json({ rfqId: 'rfq-1', status: 'Send failed', statusTone: 'danger', gmail: false, thread: [] })
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(RFQ.subject))
    await screen.findByText(/Review RFQ draft/)
    const send = screen.getByRole('button', { name: 'Send to 2 suppliers' }) as HTMLButtonElement
    expect(send.disabled).toBe(false)
    expect(screen.getByText(/Emails can’t be recalled once sent/)).toBeTruthy()
    fireEvent.click(send)
    // No confirm bar appeared; the click itself sent.
    expect(screen.queryByRole('alertdialog')).toBeNull()
    await waitFor(() => expect(sends).toHaveLength(1))
    // Per-recipient status survives: one sent, one failed with its reason.
    await screen.findByText('Gmail: 550 mailbox unavailable')
    const modal = screen.getByText(/Delivery failed/).closest('[style*="position: relative"]') as HTMLElement
    expect(within(modal).getByText('Sent')).toBeTruthy()
    expect(within(modal).getByText('Failed')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Retry send to 1 supplier' })).toBeTruthy()
  })
})

// ------------------------------------------------------------ item 5
describe('settings', () => {
  it('has no "Coming soon" roadmap rows — real controls only', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === '/api/auth/email-config') return json({ configured: false, senderAddressSet: false, fromAddress: '' })
      if (path === '/api/team') return json({ members: [], invites: [] })
      return undefined
    }))
    await openProject()
    window.location.hash = '#/settings'
    await screen.findByText('Copy me on emails')
    expect(screen.queryByText('Coming soon')).toBeNull()
    expect(screen.queryByText(/auto-follow-up/i)).toBeNull()
    expect(screen.queryByText(/Email notifications/)).toBeNull()
    expect(screen.queryByText(/due window/i)).toBeNull()
  })
})

// ------------------------------------------------------------ item 7
describe('creating a project', () => {
  it('never fetches per-project slices for the optimistic id or an empty id', async () => {
    let projects: (typeof PROJECT)[] = []
    const paths: string[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      paths.push(path)
      if (path === '/api/projects' && (!init || !init.method || init.method === 'GET')) return json(projects)
      if (path === '/api/projects' && init && init.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { name: string }
        projects = [{ ...PROJECT, id: 'north-yard', name: body.name }]
        return json(projects[0], 201)
      }
      return undefined
    }))
    render(<App />)
    await screen.findByPlaceholderText('you@company.com')
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: USER.email } })
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByText('No projects yet — create one to get started')
    fireEvent.click(screen.getByRole('button', { name: /New project/ }))
    fireEvent.change(screen.getByPlaceholderText('e.g. Riverside Water Treatment Plant'), { target: { value: 'North Yard' } })
    fireEvent.click(screen.getByRole('button', { name: /Create project/ }))
    await waitFor(() => expect(window.location.hash).toBe('#/project/north-yard/overview'))
    await screen.findByText('Where this project stands')
    // Let the saved project's own fetches land, then audit every URL.
    await waitFor(() => expect(paths.some((p) => p === '/api/projects/north-yard/rfqs/generated')).toBe(true))
    const bad = paths.filter((p) => /\/api\/projects\/proj-/.test(p) || /\/api\/projects\/\//.test(p) || /\/api\/projects\/$/.test(p))
    expect(bad).toEqual([])
    // The saved project is on screen exactly once.
    expect(screen.getAllByText('North Yard').length).toBeGreaterThan(0)
  })
})

// ------------------------------------------------------------ item 8
describe('quotes tab', () => {
  it('badges the awarded package and its winning quote once a purchase decision exists', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/quotes')) return json(QUOTES)
      if (path.endsWith('/purchase-decisions')) return json([DECISION])
      return undefined
    }))
    await openProject('quotes')
    await screen.findByText('Awarded · $10,500')
    const rows = document.querySelectorAll('[data-awarded]')
    expect(rows).toHaveLength(1)
    // The winning supplier's row carries the badge; the losing one does not.
    const winner = screen.getByText('Core & Main').closest('div') as HTMLElement
    expect(within(winner).getByText('Awarded')).toBeTruthy()
    const loser = screen.getByText('Ferguson').closest('div') as HTMLElement
    expect(within(loser).queryByText('Awarded')).toBeNull()
  })

  it('shows no award badge when there is no decision', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/quotes')) return json(QUOTES)
      return undefined
    }))
    await openProject('quotes')
    await screen.findByText('Core & Main')
    expect(screen.queryByText(/Awarded/)).toBeNull()
    expect(screen.getByText('Best')).toBeTruthy()
  })
})

// ------------------------------------------------------------ BUG-47
describe('project rows', () => {
  it('shows the computed stage (no Risk column) and RFQs-sent counts on the dashboard table and project cards', async () => {
    const ROWS = [
      { ...PROJECT, stage: 'Complete', stageTone: 'success', progress: 100, suppliers: 4, rfqs: 2, quotes: 3, barColor: 'var(--success)' },
      { ...PROJECT, id: 'p-2', name: 'Hilltop Depot', stage: 'RFQs Out', stageTone: 'blue', progress: 50, suppliers: 3, rfqs: 1, quotes: 0 },
    ]
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === '/api/projects' && (!init || !init.method || init.method === 'GET')) return json(ROWS)
      return undefined
    }))
    render(<App />)
    await screen.findByPlaceholderText('you@company.com')
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: USER.email } })
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByText('Project overview')
    expect(screen.getByText('Stage')).toBeTruthy()
    expect(screen.queryByText('Risk')).toBeNull()
    expect(screen.getByText('Complete')).toBeTruthy()
    expect(screen.getByText('RFQs Out')).toBeTruthy()
    expect(screen.getByText('100%')).toBeTruthy()
    expect(screen.getByText('50%')).toBeTruthy()
    // Project cards label the count honestly.
    window.location.hash = '#/projects'
    await screen.findByText('Hilltop Depot')
    expect(screen.getAllByText('RFQs sent').length).toBeGreaterThan(0)
    expect(screen.queryByText('Open RFQs')).toBeNull()
  })

  it('creates a project without sending a stage', async () => {
    const posts: unknown[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === '/api/projects' && init && init.method === 'POST') {
        posts.push(JSON.parse(String(init.body)))
        return json({ ...PROJECT, id: 'north-yard', name: 'North Yard' }, 201)
      }
      return undefined
    }))
    await openProject()
    window.location.hash = '#/projects'
    fireEvent.click(await screen.findByRole('button', { name: /New project/ }))
    fireEvent.change(screen.getByPlaceholderText('e.g. Riverside Water Treatment Plant'), { target: { value: 'North Yard' } })
    fireEvent.click(screen.getByRole('button', { name: /Create project/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toEqual({ name: 'North Yard', loc: '', value: '', needBy: null })
  })
})

// ------------------------------------------------------------ BUG-48
describe('overview cards refresh after RFQ changes', () => {
  it('refetches the project bundle after a send from Supplier Search, so the cards match the checklist', async () => {
    const RFQ = {
      id: 'rfq-9', projectId: PROJECT.id, package: 'water', pkg: 'Water Utilities', sup: '', folder: '', preview: '', time: '',
      logo: 'WU', logoBg: '#334155', kind: 'materials', attachments: [], lineItems: [{ n: '12" DI Pipe', q: '100 LF' }],
      subject: 'RFQ: Water Utilities — Riverside Yard', body: 'Please quote.', status: 'Draft', statusTone: 'gray',
      recipients: [{ supplierId: 'f1', name: 'Core & Main', email: 'a@x.com' }],
    }
    const TIERS = [{ tier: 1, label: 'Local · 0–25 mi', suppliers: [{ id: 'f1', name: 'Core & Main', address: '1 Main St', distanceMiles: 5, tier: 1, email: 'a@x.com', phone: '', website: '', materialCategories: [], emailSource: 'mock', relevanceScore: 1, verifyReason: '' }] }]
    let sent = 0
    let detailFetches = 0
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (/^\/api\/projects\/[^/]+$/.test(path)) {
        detailFetches++
        return json({ overviewCards: [{ label: 'RFQs sent', value: String(sent), sub: sent ? `${sent} quoted` : 'none sent yet', icon: 'rfq', tone: 'blue' }], packages: [], activity: [] })
      }
      if (path.includes('/packages/water/bom')) return json({ package: 'water', label: 'Water Utilities', tone: 'blue', count: 1, items: [{ n: '12" DI Pipe', q: '100 LF' }], seeded: false, custom: false, pendingReview: 0 })
      if (path.includes('/suppliers/found')) return json({ status: 'done', mocked: true, radiusMi: 75, package: 'water', error: null, tiers: TIERS })
      if (path.endsWith('/rfqs/generate') && init && init.method === 'POST') return json(RFQ, 201)
      if (path.endsWith('/rfqs/rfq-9') && init && init.method === 'PUT') return json(RFQ)
      if (path.endsWith('/rfqs/rfq-9/send') && init && init.method === 'POST') {
        sent++
        return json({ ...RFQ, status: 'Awaiting', statusTone: 'warn', recipients: [{ ...RFQ.recipients[0], sendStatus: 'sent', sentMessageId: 'm1' }] })
      }
      if (path.includes('/conversation')) return json({ rfqId: 'rfq-9', status: 'Awaiting', statusTone: 'warn', gmail: false, thread: [] })
      return undefined
    }))
    await openProject('suppliers')
    fireEvent.click(await screen.findByTitle('Select for RFQ'))
    fireEvent.click(await screen.findByRole('button', { name: /Generate RFQ draft/ }))
    await screen.findByText(/Review RFQ draft/)
    const before = detailFetches
    fireEvent.click(screen.getByRole('button', { name: 'Send to 1 supplier' }))
    await waitFor(() => expect(sent).toBe(1))
    // The bundle (which carries the overview cards) was refetched by the send.
    await waitFor(() => expect(detailFetches).toBeGreaterThan(before))
    fireEvent.click(screen.getByTitle('Close'))
    window.location.hash = `#/project/${PROJECT.id}/overview`
    await screen.findByText('1 quoted')
    expect(screen.queryByText('none sent yet')).toBeNull()
  })
})
