// Client for the dev-only `/bench/*` API (docs/eval-harness.md §3).
//
// No auth: the bench router is unauthenticated and mounted only outside
// production, so there is no token to attach.
import type {
  CompareOut, CorpusOut, CreateRunBody, CreateRunOut, PlanTypeOut,
  RunDetailOut, RunSummaryOut, StatusOut, VariantOut,
} from './types'

const BASE = import.meta.env.VITE_BENCH_API_URL || 'http://localhost:8040'

// ------------------------------------------------------------------ mock switch
// THE one switch for the fixture adapter. `import.meta.env.DEV` is substituted
// at build time, so a production bundle folds this to `false` and Rollup drops
// the `import('./mock')` below entirely — the fixtures cannot be reached from a
// built app, and a normal `npm run dev` needs the flag to be set on purpose.
export const MOCK: boolean =
  import.meta.env.DEV &&
  (import.meta.env.VITE_BENCH_MOCK === '1' ||
    (typeof location !== 'undefined' && new URLSearchParams(location.search).get('mock') === '1'))

export const API_BASE = BASE

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (MOCK) {
    const mock = await import('./mock')
    return mock.mockRequest<T>(path, init)
  }
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...(init?.headers || {}) } : init?.headers,
  })
  if (!res.ok) {
    // Surface FastAPI's `detail` rather than a bare status code.
    const data = await res.json().catch(() => null)
    const detail = data && typeof data.detail === 'string' ? data.detail : null
    throw new Error(detail || `${path} → ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const getStatus = () => request<StatusOut>('/bench/status')
export const getCorpus = () => request<CorpusOut>('/bench/corpus')
export const getPlanTypes = () => request<PlanTypeOut[]>('/bench/plan-types')
export const getVariants = () => request<VariantOut[]>('/bench/variants')

export const createRuns = (body: CreateRunBody) =>
  request<CreateRunOut>('/bench/runs', { method: 'POST', body: JSON.stringify(body) })

export const listRuns = (limit = 50) => request<RunSummaryOut[]>(`/bench/runs?limit=${limit}`)
export const getRun = (id: string) => request<RunDetailOut>(`/bench/runs/${encodeURIComponent(id)}`)

export const cancelRun = (id: string) =>
  request<{ cancelled: boolean }>(`/bench/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })

export const deleteRun = (id: string) =>
  request<{ deleted: boolean }>(`/bench/runs/${encodeURIComponent(id)}`, { method: 'DELETE' })

export const compareRuns = (a: string, b: string) =>
  request<CompareOut>(`/bench/runs/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`)
