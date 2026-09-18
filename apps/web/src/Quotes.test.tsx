// Quotes → compare → award reliability: the compare link carries the package
// KEY (a custom BOM's document id) rather than its label, an already-awarded
// package needs an explicit re-award, and sending a draft from the RFQs tab
// updates the list in place. Drives the real <App /> against a mocked fetch.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import App from './App'

const USER = { id: 'u-pm', email: 'pm@acmebuild.com', name: 'PM', company: 'Acme Build Co.', ccEmail: null }

const PROJECT = {
  id: 'p-1', name: 'Riverside Yard', loc: 'Austin, TX', stage: 'Plans Review',
  stageTone: 'gray', value: '$1.0M', progress: 0, suppliers: 0, rfqs: 0, quotes: 0,
  risk: 'Low', riskTone: 'success', barColor: 'var(--primary)',
}

// Two quotes for a custom BOM whose package key is its document id.
const QUOTES = [
  { id: 'q1', sup: 'Alpha Supply', pkg: 'QA Custom BOM', package: 'upload-16-abc123', amount: '$1,000', freight: '$50', total: '$1,050', lead: '5 days', date: 'Sep 01', logo: 'AS', logoBg: '#333', best: true },
  { id: 'q2', sup: 'Beta Pipe', pkg: 'QA Custom BOM', package: 'upload-16-abc123', amount: '$1,200', freight: '$20', total: '$1,220', lead: '3 days', date: 'Sep 01', logo: 'BP', logoBg: '#444', best: false },
]

const LINE_COMPARISON = {
  pkg: 'QA Custom BOM', package: 'upload-16-abc123', budget: null,
  suppliers: [
    { id: 's1', name: 'Alpha Supply', logo: 'AS', logoBg: '#333', leadDays: 5, distanceMiles: 10, freight: 50, total: 1050 },
    { id: 's2', name: 'Beta Pipe', logo: 'BP', logoBg: '#444', leadDays: 3, distanceMiles: 30, freight: 20, total: 1220 },
  ],
  lines: [{ name: 'Fire hydrant', qty: '5 EA', cells: [
    { supplierId: 's1', unitPrice: 200, extended: 1000, leadDays: 5, available: true, best: true },
    { supplierId: 's2', unitPrice: 240, extended: 1200, leadDays: 3, available: true, best: false },
  ], bestSupplierId: 's1', pending: false }],
  options: [
    { key: 'mix', label: 'Lowest cost', total: 1050, material: 1000, freight: 50, leadDays: 5, suppliersUsed: 1, deliveries: 1, maxDistance: 10, savings: 0, note: '', selections: { 'Fire hydrant': 's1' } },
    { key: 'single', label: 'Single supplier', total: 1050, material: 1000, freight: 50, leadDays: 5, suppliersUsed: 1, deliveries: 1, maxDistance: 10, savings: 0, note: '', selections: { 'Fire hydrant': 's1' } },
  ],
  recommendedOption: 'mix',
  lastAward: null as null | object,
}

const DRAFT_RFQ = {
  id: 'rfq-1', projectId: 'p-1', package: 'upload-16-abc123', pkg: 'QA Custom BOM', folder: 'Draft',
  status: 'Draft', statusTone: 'gray', preview: 'b', time: '—', unread: false, logo: 'RF', logoBg: '#334155',
  subject: 'RFQ: QA Custom BOM — Riverside Yard', body: 'Please quote.', lineItems: [], kind: 'materials',
  attachments: [], recipients: [{ supplierId: 's1', name: 'Alpha Supply', email: 'a@example.com' }], sentAt: null,
}

let lineComparison = LINE_COMPARISON
let rfqs: object[] = []
const comparisonRequests: string[] = []
const awardRequests: string[] = []
const awardBodies: { supersede?: boolean }[] = []
// When set, the conversation endpoint waits on this before answering.
let holdConversation: Promise<void> | null = null
let conversationStatus = 'Awaiting'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input instanceof Request ? input.url : input)
  const path = url.replace(/^https?:\/\/[^/]+/, '')
  const method = (init && init.method) || 'GET'

  if (path === '/api/auth/login') return json({ accessToken: 'tok', user: USER })
  if (path === '/api/auth/me') return json(USER)
  if (path === '/api/dashboard') return json({ metrics: [], activity: [] })
  if (path === '/api/projects') return json([PROJECT])
  if (path === '/api/suppliers') return json([])
  if (path === '/api/documents/plan-types') return json([])
  if (path.endsWith('/quotes')) return json(QUOTES)
  const lcm = path.match(/\/packages\/([^/]+)\/line-comparison$/)
  if (lcm) { comparisonRequests.push(decodeURIComponent(lcm[1])); return json(lineComparison) }
  const aw = path.match(/\/packages\/([^/]+)\/award$/)
  if (aw && method === 'POST') {
    awardRequests.push(decodeURIComponent(aw[1]))
    awardBodies.push(JSON.parse(String(init && init.body)))
    return json({ status: 'awarded', message: 'Awarded QA Custom BOM for $1,050 — 1 PO to Alpha Supply.', total: 1050, material: 1000, freight: 50, leadDays: 5, suppliers: ['Alpha Supply'], poCount: 1 })
  }
  if (path.endsWith('/rfqs/generated')) return json(rfqs)
  const put = path.match(/\/rfqs\/([^/]+)$/)
  if (put && method === 'PUT') {
    const body = JSON.parse(String(init && init.body))
    rfqs = rfqs.map((r) => ((r as { id: string }).id === put[1] ? { ...r, ...body } : r))
    return json(rfqs.find((r) => (r as { id: string }).id === put[1]))
  }
  const send = path.match(/\/rfqs\/([^/]+)\/send$/)
  if (send && method === 'POST') {
    rfqs = rfqs.map((r) => ((r as { id: string }).id === send[1] ? { ...r, status: 'Awaiting', statusTone: 'warn', folder: 'Awaiting', sentAt: '2026-09-17T00:00:00Z', time: 'Sep 17' } : r))
    return json(rfqs.find((r) => (r as { id: string }).id === send[1]))
  }
  if (path.includes('/conversation')) {
    if (holdConversation) await holdConversation
    return json({ rfqId: 'rfq-1', status: conversationStatus, statusTone: 'warn', gmail: false, thread: [] })
  }
  if (path.includes('/timeline')) return json({ milestones: [], gantt: [], ganttCols: [] })
  if (path.includes('/comparison')) return json({ suppliers: [], rows: [], recommendation: '', reasons: [], savings: '', savingsNote: '' })
  if (/^\/api\/projects\/[^/]+$/.test(path)) return json({ overviewCards: [], packages: [], activity: [] })
  return json([])
})

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', window.location.pathname)
  lineComparison = { ...LINE_COMPARISON, lastAward: null }
  rfqs = [DRAFT_RFQ]
  comparisonRequests.length = 0
  awardRequests.length = 0
  awardBodies.length = 0
  holdConversation = null
  conversationStatus = 'Awaiting'
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

describe('quotes → compare → award', () => {
  it('compares a custom package by its key, not its label', async () => {
    await openProject()
    fireEvent.click(screen.getByRole('button', { name: /Quotes/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Compare/ }))
    await screen.findByText(/QA Custom BOM — Quote Comparison/)
    // The label-based request used to 404 ("No quotes to compare for package").
    expect(comparisonRequests).toEqual(['upload-16-abc123'])
    expect(window.location.hash).toBe('#/project/p-1/quotes/compare/upload-16-abc123')
  })

  it('turns the submit button into a confirmed "Award again" after a successful award', async () => {
    await openProject()
    fireEvent.click(screen.getByRole('button', { name: /Quotes/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Compare/ }))
    const submit = await screen.findByRole('button', { name: /Submit award/ })
    fireEvent.click(submit)
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Confirm award' }))
    await screen.findByText(/Awarded QA Custom BOM/)
    expect(awardRequests).toEqual(['upload-16-abc123'])
    // No plain submit any more: the package is flagged as awarded and a second
    // click only opens the re-award confirm (no request without it).
    expect(screen.queryByRole('button', { name: /Submit award/ })).toBeNull()
    await screen.findByText(/Already awarded/)
    fireEvent.click(screen.getByRole('button', { name: /Award again/ }))
    await screen.findByRole('alertdialog')
    expect(awardRequests).toEqual(['upload-16-abc123'])
  })

  it('requires an explicit re-award when the package was already awarded', async () => {
    lineComparison = { ...LINE_COMPARISON, lastAward: { decidedAt: '2026-09-10T12:00:00Z', decidedByEmail: 'pm@acmebuild.com', suppliers: ['Alpha Supply'], total: 1050, poCount: 1 } }
    await openProject()
    fireEvent.click(screen.getByRole('button', { name: /Quotes/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Compare/ }))
    await screen.findByText(/Already awarded/)
    expect(screen.queryByRole('button', { name: /Submit award/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Award again/ }))
    const bar = await screen.findByRole('alertdialog')
    expect(bar.textContent).toContain('already awarded')
    fireEvent.click(within(bar).getByRole('button', { name: 'Award again' }))
    await waitFor(() => expect(awardRequests).toEqual(['upload-16-abc123']))
    // The backend refuses a repeat award without this flag.
    expect(awardBodies[0].supersede).toBe(true)
  })

  it('sends a first award without supersede', async () => {
    await openProject()
    fireEvent.click(screen.getByRole('button', { name: /Quotes/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Compare/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Submit award/ }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Confirm award' }))
    await waitFor(() => expect(awardBodies).toHaveLength(1))
    expect(awardBodies[0].supersede).toBe(false)
  })
})

describe('RFQ modal status', () => {
  it('never rolls a just-sent RFQ back to an older status from the conversation read', async () => {
    // The conversation endpoint answers with a status behind the RFQ record
    // (a stale/lagging read). The modal must keep the authoritative post-send
    // status rather than regress to what the thread reports.
    conversationStatus = 'Draft'
    await openProject()
    fireEvent.click(screen.getByRole('button', { name: /^RFQs$/ }))
    fireEvent.click(await screen.findByText(DRAFT_RFQ.subject))
    fireEvent.click(await screen.findByRole('button', { name: /Send RFQ/ }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Send now' }))
    await waitFor(() => expect(rfqs[0]).toMatchObject({ status: 'Awaiting' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/conversation')).length).toBeGreaterThan(0))
    await new Promise((r) => setTimeout(r, 50))
    // Modal badge + list row both show the post-send status; nothing says Draft.
    expect(screen.getAllByText('Awaiting').length).toBeGreaterThan(0)
    expect(screen.queryByText('Draft')).toBeNull()
  })
})

describe('RFQs tab', () => {
  it('updates the list row as soon as a draft is sent from the review modal', async () => {
    await openProject()
    fireEvent.click(screen.getByRole('button', { name: /^RFQs$/ }))
    fireEvent.click(await screen.findByText(DRAFT_RFQ.subject))
    fireEvent.click(await screen.findByRole('button', { name: /Send RFQ/ }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Send now' }))
    // The modal is still open; the list behind it already shows the new status.
    await waitFor(() => expect(screen.getAllByText('Awaiting').length).toBeGreaterThan(0))
    expect(screen.queryByText('Draft')).toBeNull()
  })
})
