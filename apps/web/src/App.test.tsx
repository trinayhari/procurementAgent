// Regression tests for cross-account workspace leakage (fix/stale-user-data-and-jitter).
//
// The bug: logging in after another account had used the same tab rendered the
// previous account's dashboard (projects, metrics, activity) until the new
// account's workspace bundle finished loading — or indefinitely, if that load
// failed. These tests drive the real <App /> against a mocked fetch whose
// workspace endpoints can be held open, simulating the network window in which
// the leak was visible.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import App from './App'

type MockUser = { id: string; email: string; name: string; company: string; ccEmail: string | null }

const USERS: Record<string, MockUser> = {
  'alice@acmebuild.com': { id: 'u-alice', email: 'alice@acmebuild.com', name: 'Alice Field', company: 'Acme Build Co.', ccEmail: null },
  'bob@rivera.com': { id: 'u-bob', email: 'bob@rivera.com', name: 'Bob Rivera', company: 'Rivera Constructors', ccEmail: null },
}

const PROJECTS: Record<string, object[]> = {
  'u-alice': [{
    id: 'p-alice', name: 'ALICE SECRET DAM PROJECT', loc: 'Boulder, CO', stage: 'Plans Review',
    stageTone: 'gray', value: '$4.2M', progress: 0, suppliers: 0, rfqs: 0, quotes: 0,
    risk: 'Low', riskTone: 'success', barColor: 'var(--primary)',
  }],
  'u-bob': [],
}

// When set, every workspace (non-auth) request awaits this promise before
// responding — the test's stand-in for real network latency.
let holdData: Promise<void> | null = null

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input instanceof Request ? input.url : input)
  const path = url.replace(/^https?:\/\/[^/]+/, '')
  const headers = (init && (init.headers as Record<string, string>)) || {}
  const uid = (headers.Authorization || '').replace('Bearer tok-', '')

  if (path === '/api/auth/login') {
    const body = JSON.parse(String(init && init.body))
    const u = USERS[body.email]
    if (!u) return json({ detail: 'Invalid email or password' }, 401)
    return json({ accessToken: `tok-${u.id}`, user: u })
  }
  if (path === '/api/auth/me') {
    const u = Object.values(USERS).find((x) => x.id === uid)
    return u ? json(u) : json({ detail: 'unauthorized' }, 401)
  }

  if (holdData) await holdData

  if (path === '/api/dashboard') return json({ metrics: [], activity: [] })
  if (path === '/api/projects') return json(PROJECTS[uid] || [])
  if (path === '/api/suppliers') return json([])
  if (path === '/api/documents/plan-types') return json([])
  if (path.includes('/timeline')) return json({ milestones: [], gantt: [], ganttCols: [] })
  if (path.includes('/comparison')) return json({ suppliers: [], rows: [], recommendation: '', reasons: [], savings: '', savingsNote: '' })
  if (/^\/api\/projects\/[^/]+$/.test(path)) return json({ overviewCards: [], packages: [], activity: [] })
  if (/^\/api\/suppliers\/[^/]+$/.test(path)) return json({ comms: [] })
  return json([])
})

async function signIn(email: string) {
  fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: email } })
  fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

async function signOut() {
  fireEvent.click(screen.getByTitle('Sign out'))
  await screen.findByPlaceholderText('you@company.com')
}

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', window.location.pathname)
  holdData = null
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('account switching', () => {
  it("never renders the previous account's workspace after a different user signs in", async () => {
    render(<App />)
    await screen.findByPlaceholderText('you@company.com')

    await signIn('alice@acmebuild.com')
    await screen.findByText('ALICE SECRET DAM PROJECT')

    await signOut()

    // Bob signs in while his workspace fetches are held open — the window in
    // which the old code painted Alice's dashboard under Bob's session.
    let release!: () => void
    holdData = new Promise<void>((r) => { release = r })
    await signIn('bob@rivera.com')
    await waitFor(() => expect(screen.queryByPlaceholderText('you@company.com')).toBeNull())

    expect(screen.queryByText('ALICE SECRET DAM PROJECT')).toBeNull()
    expect(screen.queryByText(/Good (morning|afternoon|evening), Alice/)).toBeNull()

    release()
    holdData = null
    await screen.findByText(/Good (morning|afternoon|evening), Bob/)
    expect(screen.queryByText('ALICE SECRET DAM PROJECT')).toBeNull()
    // A different account never inherits the previous account's route.
    expect(window.location.hash).toBe('#/dashboard')
  })

  it('resumes the previous location when the same account signs back in', async () => {
    render(<App />)
    await screen.findByPlaceholderText('you@company.com')

    await signIn('alice@acmebuild.com')
    fireEvent.click(await screen.findByText('ALICE SECRET DAM PROJECT'))
    await waitFor(() => expect(window.location.hash).toBe('#/project/p-alice/overview'))

    await signOut()
    await signIn('alice@acmebuild.com')

    await waitFor(() => expect(window.location.hash).toBe('#/project/p-alice/overview'))
    expect(await screen.findAllByText('ALICE SECRET DAM PROJECT')).not.toHaveLength(0)
  })
})
