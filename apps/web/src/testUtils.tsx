// Shared scaffolding for the App-level flow tests: a signed-in user, one
// project, and a fetch mock that answers the workspace bundle with empty
// slices unless a test overrides a path. Mirrors the pattern in App.test.tsx
// so each suite only has to describe the data its flow needs.
import { vi, expect } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from './App'

export const USER = { id: 'u-pm', email: 'pm@acmebuild.com', name: 'Pat Mason', company: 'Acme Build Co.', ccEmail: null }

export const PROJECT = {
  id: 'p-1', name: 'Riverside Yard', loc: 'Austin, TX', stage: 'Plans Review',
  stageTone: 'gray', value: '$1.0M', progress: 0, suppliers: 0, rfqs: 0, quotes: 0,
  risk: 'Low', riskTone: 'success', barColor: 'var(--primary)',
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

export type Route = (path: string, init?: RequestInit) => Response | Promise<Response> | undefined

// Build a fetch mock. `routes` is consulted first (return undefined to fall
// through); the defaults answer auth + an empty workspace.
export function makeFetch(routes: Route): ReturnType<typeof vi.fn> {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input instanceof Request ? input.url : input)
    const path = url.replace(/^https?:\/\/[^/]+/, '')
    const hit = await routes(path, init)
    if (hit) return hit
    if (path === '/api/auth/login') return json({ accessToken: 'tok', user: USER })
    if (path === '/api/auth/me') return json(USER)
    if (path === '/api/dashboard') return json({ metrics: [], activity: [] })
    if (path === '/api/projects' && (!init || !init.method || init.method === 'GET')) return json([PROJECT])
    if (path === '/api/suppliers') return json([])
    if (path === '/api/documents/plan-types') return json([])
    if (path.includes('/timeline')) return json({ milestones: [], gantt: [], ganttCols: [] })
    if (path.includes('/comparison')) return json({ suppliers: [], rows: [], recommendation: '', reasons: [], savings: '', savingsNote: '' })
    if (/^\/api\/projects\/[^/]+$/.test(path)) return json({ overviewCards: [], packages: [], activity: [] })
    if (path.endsWith('/purchase-decisions')) return json([])
    if (path.includes('/suppliers/found')) return json({ status: 'idle', mocked: false, radiusMi: 0, package: '', error: null, tiers: [] })
    if (path.endsWith('/boms') || path.endsWith('/trades')) return json([])
    return json([])
  })
}

// Sign in and land on the project's given tab.
export async function openProject(tab = 'overview') {
  render(<App />)
  await screen.findByPlaceholderText('you@company.com')
  fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: USER.email } })
  fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  fireEvent.click(await screen.findByText(PROJECT.name))
  await waitFor(() => expect(window.location.hash).toBe(`#/project/${PROJECT.id}/overview`))
  if (tab !== 'overview') {
    window.location.hash = `#/project/${PROJECT.id}/${tab}`
    await waitFor(() => expect(window.location.hash).toBe(`#/project/${PROJECT.id}/${tab}`))
  }
}

export function resetDom() {
  localStorage.clear()
  window.history.replaceState(null, '', window.location.pathname)
}
