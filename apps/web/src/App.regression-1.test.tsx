// Regression: ISSUE-001 — a project id that isn't in the account's list rendered
// a *different* project's workspace (name, value, tabs, delete action) instead of
// a not-found state, because both model.ts (activeProject) and api.ts (which
// project to hydrate) fell back to projects[0].
// Found by /qa on 2026-08-10
// Report: .gstack/qa-reports/qa-report-localhost-2026-08-10.md
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import App from './App'

type MockUser = { id: string; email: string; name: string; company: string; ccEmail: string | null }

const USER: MockUser = {
  id: 'u-dana', email: 'dana@northbuild.com', name: 'Dana Ortiz',
  company: 'North Build Co.', ccEmail: null,
}

const REAL_PROJECT = {
  id: 'p-real', name: 'NORTH RIDGE PUMP STATION', loc: 'Reno, NV', stage: 'Plans Review',
  stageTone: 'gray', value: '$9.1M', progress: 0, suppliers: 0, rfqs: 0, quotes: 0,
  risk: 'Low', riskTone: 'success', barColor: 'var(--primary)',
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input instanceof Request ? input.url : input)
  const path = url.replace(/^https?:\/\/[^/]+/, '')
  const headers = (init && (init.headers as Record<string, string>)) || {}
  const uid = (headers.Authorization || '').replace('Bearer tok-', '')

  if (path === '/api/auth/login') return json({ accessToken: `tok-${USER.id}`, user: USER })
  if (path === '/api/auth/me') return uid === USER.id ? json(USER) : json({ detail: 'unauthorized' }, 401)

  if (path === '/api/dashboard') return json({ metrics: [], activity: [] })
  if (path === '/api/projects') return json([REAL_PROJECT])
  if (path === '/api/suppliers') return json([])
  if (path === '/api/documents/plan-types') return json([])
  if (path.includes('/timeline')) return json({ milestones: [], gantt: [], ganttCols: [] })
  if (path.includes('/comparison')) return json({ suppliers: [], rows: [], recommendation: '', reasons: [], savings: '', savingsNote: '' })
  // The backend 404s an id the account doesn't own; the old client never asked.
  if (/^\/api\/projects\/[^/]+$/.test(path)) {
    const id = path.split('/').pop()
    if (id !== REAL_PROJECT.id) return json({ detail: 'Project not found' }, 404)
    return json({ overviewCards: [], packages: [], activity: [] })
  }
  if (/^\/api\/suppliers\/[^/]+$/.test(path)) return json({ comms: [] })
  return json([])
})

async function signIn() {
  fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: USER.email } })
  fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

// Open a project by URL the way a bookmarked or shared link does.
async function openByHash(id: string) {
  window.location.hash = `#/project/${id}/overview`
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

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

describe('unknown project id', () => {
  it('renders a not-found state instead of another project when the id is unknown', async () => {
    render(<App />)
    await screen.findByPlaceholderText('you@company.com')
    await signIn()
    await screen.findByText('NORTH RIDGE PUMP STATION')
    await openByHash('p-deleted')

    expect(await screen.findByText('Project not found')).toBeTruthy()
    // The precondition that made this a leak: another project DOES exist, and it
    // is what the old fallback painted under the requested URL.
    expect(screen.queryByText('NORTH RIDGE PUMP STATION')).toBeNull()
    expect(screen.queryByText(/\$9\.1M/)).toBeNull()
    // The workspace chrome (and its destructive Delete action) must stay hidden.
    expect(screen.queryByTitle('Delete project')).toBeNull()
  })

  it('never asks the backend for a different project than the one in the URL', async () => {
    render(<App />)
    await screen.findByPlaceholderText('you@company.com')
    await signIn()
    await screen.findByText('NORTH RIDGE PUMP STATION')
    fetchMock.mockClear()
    await openByHash('p-deleted')
    await screen.findByText('Project not found')

    const detailCalls = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .filter((u) => /\/api\/projects\/[^/]+$/.test(u))
    expect(detailCalls.some((u) => u.endsWith(`/api/projects/${REAL_PROJECT.id}`))).toBe(false)
  })

  it('still opens a project that does exist', async () => {
    render(<App />)
    await screen.findByPlaceholderText('you@company.com')
    await signIn()
    await screen.findByText('NORTH RIDGE PUMP STATION')
    await openByHash(REAL_PROJECT.id)

    expect(await screen.findAllByText('NORTH RIDGE PUMP STATION')).not.toHaveLength(0)
    expect(screen.queryByText('Project not found')).toBeNull()
  })

  it('recovers to the projects list from the not-found state', async () => {
    render(<App />)
    await screen.findByPlaceholderText('you@company.com')
    await signIn()
    await screen.findByText('NORTH RIDGE PUMP STATION')
    await openByHash('p-deleted')
    await screen.findByText('Project not found')

    fireEvent.click(await screen.findByRole('button', { name: 'Back to projects' }))
    await waitFor(() => expect(window.location.hash).toBe('#/projects'))
    expect(await screen.findAllByText('NORTH RIDGE PUMP STATION')).not.toHaveLength(0)
  })
})
