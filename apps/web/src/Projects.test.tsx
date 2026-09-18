// Project lifecycle reliability: a deep link to a project that no longer
// exists must not wedge the app on the loading splash, and deleting a project
// must drop it from the list without a hard reload. Drives the real <App />
// against a mocked fetch (see App.test.tsx).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import App from './App'

const USER = { id: 'u-pm', email: 'pm@acmebuild.com', name: 'PM', company: 'Acme Build Co.', ccEmail: null }

const project = (id: string, name: string) => ({
  id, name, loc: 'Austin, TX', stage: 'Plans Review', stageTone: 'gray', value: '$1.0M',
  progress: 0, suppliers: 0, rfqs: 0, quotes: 0, risk: 'Low', riskTone: 'success', barColor: 'var(--primary)',
})

let projects = [project('p-1', 'Riverside Yard'), project('p-2', 'Hilltop Depot')]
const deleteCalls: string[] = []

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input instanceof Request ? input.url : input)
  const path = url.replace(/^https?:\/\/[^/]+/, '')
  const method = (init && init.method) || 'GET'

  if (path === '/api/auth/login') return json({ accessToken: 'tok', user: USER })
  if (path === '/api/auth/me') return json(USER)
  if (path === '/api/dashboard') return json({ metrics: [], activity: [] })
  if (path === '/api/projects') return json(projects)
  if (path === '/api/suppliers') return json([])
  if (path === '/api/documents/plan-types') return json([])
  const del = path.match(/^\/api\/projects\/([^/]+)$/)
  if (del && method === 'DELETE') {
    deleteCalls.push(del[1])
    projects = projects.filter((p) => p.id !== del[1])
    return new Response(null, { status: 204 })
  }
  if (/^\/api\/projects\/[^/]+$/.test(path)) {
    const id = path.split('/').pop()
    return projects.some((p) => p.id === id)
      ? json({ overviewCards: [], packages: [], activity: [] })
      : json({ detail: 'Project not found' }, 404)
  }
  if (path.includes('/timeline')) return json({ milestones: [], gantt: [], ganttCols: [] })
  if (path.includes('/comparison')) return json({ suppliers: [], rows: [], recommendation: '', reasons: [], savings: '', savingsNote: '' })
  return json([])
})

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('procureai_token', 'tok')
  window.history.replaceState(null, '', window.location.pathname)
  projects = [project('p-1', 'Riverside Yard'), project('p-2', 'Hilltop Depot')]
  deleteCalls.length = 0
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('project lifecycle', () => {
  it('lands on the projects list with a notice when the URL names a project that no longer exists', async () => {
    render(<App />)
    await screen.findByText('Riverside Yard')
    // A stale link / Back to a deleted project. (Driven via a hash change after
    // mount: happy-dom replays the initial hash as a late hashchange, which
    // would clobber the app's own navigation mid-test; the reload path under
    // test is the same one an initial deep link takes.)
    window.location.hash = '#/project/does-not-exist/overview'
    // Previously: the workspace bundle for the fallback project was discarded
    // because it wasn't for the project in the URL — on an initial load that
    // left the splash spinning forever.
    await screen.findByText(/That project no longer exists/)
    await waitFor(() => expect(window.location.hash).toBe('#/projects'))
    expect(screen.getAllByText('Riverside Yard').length).toBeGreaterThan(0)
  })

  it('drops a deleted project from the list immediately', async () => {
    render(<App />)
    fireEvent.click(await screen.findByText('Hilltop Depot'))
    await waitFor(() => expect(window.location.hash).toBe('#/project/p-2/overview'))
    // Let happy-dom's asynchronous hashchange for that navigation land before
    // deleting, so it can't replay the project route after the delete.
    await new Promise((r) => setTimeout(r, 30))
    fireEvent.click(screen.getByRole('button', { name: 'Delete project' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete project' }))
    await waitFor(() => expect(deleteCalls).toEqual(['p-2']))
    await waitFor(() => expect(window.location.hash).toBe('#/projects'))
    // The refetched list no longer carries the deleted project; no notice
    // is shown for the user's own delete.
    await waitFor(() => expect(screen.queryByText('Hilltop Depot')).toBeNull())
    expect(screen.getAllByText('Riverside Yard').length).toBeGreaterThan(0)
    expect(screen.queryByText(/no longer exists/)).toBeNull()
  })
})
