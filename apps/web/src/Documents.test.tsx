// Documents tab reliability: a failed extraction explains itself and can be
// retried; a document whose stored file is gone (ephemeral disk) says so
// instead of showing a broken preview; a refused upload shows the backend's
// reason. Drives the real <App /> against a mocked fetch (see App.test.tsx).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import App from './App'

const USER = { id: 'u-pm', email: 'pm@acmebuild.com', name: 'PM', company: 'Acme Build Co.', ccEmail: null }

const PROJECT = {
  id: 'p-1', name: 'Riverside Yard', loc: 'Austin, TX', stage: 'Plans Review',
  stageTone: 'gray', value: '$1.0M', progress: 0, suppliers: 0, rfqs: 0, quotes: 0,
  risk: 'Low', riskTone: 'success', barColor: 'var(--primary)',
}

const PLAN_TYPES = [
  { key: 'site_plan', label: 'Site Plan', description: '', enabled: true, categories: ['Water'], singleton: true },
  { key: 'other', label: 'Additional Document', description: '', enabled: true, categories: [], singleton: false },
]

const FAILED_DOC = {
  id: 'doc-failed', name: 'Site Plan Rev B', type: 'Site Plan', date: 'Aug 09, 2026',
  status: 'Failed', statusTone: 'danger', items: '—', pages: 12, processing: false,
  hasFile: true, fileMissing: false, planType: 'site_plan', summary: '',
  error: 'Extraction failed: extraction subprocess exited 139 (likely a native crash while parsing the PDF)',
}

const GONE_DOC = {
  id: 'doc-gone', name: 'Old Site Plan', type: 'Site Plan', date: 'Aug 01, 2026',
  status: 'Analyzed', statusTone: 'success', items: '40', pages: 8, processing: false,
  hasFile: true, fileMissing: true, planType: 'site_plan', summary: '', error: null,
}

let docs: object[] = []
let uploadResponse: Response | null = null
let lineItems: Record<string, object[]> = {}
const analyzeCalls: string[] = []
const deleteCalls: string[] = []
const savedTo: string[] = []
const manualCreates: string[] = []

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
  if (path === '/api/documents/plan-types') return json(PLAN_TYPES)
  if (path === '/api/documents' && method === 'POST') return uploadResponse || json({ detail: 'unexpected' }, 500)
  if (path === '/api/documents/manual' && method === 'POST') {
    const body = JSON.parse(String(init && init.body))
    manualCreates.push(body.name)
    const doc = { ...GONE_DOC, id: `bom-${manualCreates.length}`, name: body.name, hasFile: false, fileMissing: false, planType: 'custom_bom', status: 'Draft', statusTone: 'gray', items: '0' }
    docs = [doc, ...docs]
    lineItems[doc.id] = [{ group: body.name, count: 0, tone: 'blue', items: [] }]
    return json(doc, 201)
  }
  const analyze = path.match(/^\/api\/documents\/([^/]+)\/analyze$/)
  if (analyze && method === 'POST') {
    analyzeCalls.push(analyze[1])
    docs = docs.map((d) => ((d as { id: string }).id === analyze[1] ? { ...d, status: 'Processing', statusTone: 'blue', processing: true, error: null } : d))
    return json(docs[0])
  }
  const del = path.match(/^\/api\/documents\/([^/]+)$/)
  if (del && method === 'DELETE') {
    deleteCalls.push(del[1])
    docs = docs.filter((d) => (d as { id: string }).id !== del[1])
    return new Response(null, { status: 204 })
  }
  const put = path.match(/^\/api\/documents\/([^/]+)\/line-items$/)
  if (put && method === 'PUT') {
    savedTo.push(put[1])
    lineItems[put[1]] = JSON.parse(String(init && init.body)).groups
    return json(lineItems[put[1]])
  }
  if (put && method === 'GET') return json(lineItems[put[1]] || [])
  if (path.endsWith('/documents')) return json(docs)
  if (path.includes('/preview')) return json({ pages: 0, pageUrl: null, fileUrl: '/x', expiresInMinutes: 15 })
  if (path.includes('/timeline')) return json({ milestones: [], gantt: [], ganttCols: [] })
  if (path.includes('/comparison')) return json({ suppliers: [], rows: [], recommendation: '', reasons: [], savings: '', savingsNote: '' })
  if (/^\/api\/projects\/[^/]+$/.test(path)) return json({ overviewCards: [], packages: [], activity: [] })
  if (path.includes('/line-items')) return json([])
  return json([])
})

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', window.location.pathname)
  docs = []
  uploadResponse = null
  lineItems = {}
  analyzeCalls.length = 0
  deleteCalls.length = 0
  savedTo.length = 0
  manualCreates.length = 0
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function openDocuments() {
  render(<App />)
  await screen.findByPlaceholderText('you@company.com')
  fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: USER.email } })
  fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'password123' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  fireEvent.click(await screen.findByText('Riverside Yard'))
  await waitFor(() => expect(window.location.hash).toBe('#/project/p-1/overview'))
  fireEvent.click(screen.getByRole('button', { name: /^Documents$/ }))
}

describe('documents tab reliability', () => {
  it('shows why an extraction failed and lets the user retry it', async () => {
    docs = [FAILED_DOC]
    await openDocuments()

    // Previously the badge said "Failed" and the stored reason was never shown.
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Analysis failed.')
    expect(alert.textContent).toContain('native crash while parsing the PDF')

    fireEvent.click(screen.getByRole('button', { name: 'Retry analysis' }))
    await waitFor(() => expect(analyzeCalls).toEqual(['doc-failed']))
    // The document is back in 'Processing' after the reload.
    await screen.findByText('Processing')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('explains a stored file that is no longer on the server', async () => {
    docs = [GONE_DOC]
    await openDocuments()
    await screen.findByText('File no longer available')
    expect(screen.getByText(/re-upload the file to preview/)).toBeTruthy()
    // No preview fetch is attempted for a file we already know is gone.
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/preview'))).toBe(false)
  })

  it("shows the backend's reason when an upload is refused", async () => {
    docs = []
    uploadResponse = json({ detail: 'Could not read this PDF — the file appears to be corrupt or incomplete' }, 400)
    await openDocuments()

    const inputs = document.querySelectorAll('input[type="file"]')
    expect(inputs.length).toBeGreaterThan(0)
    const file = new File([new Uint8Array([37, 80, 68, 70])], 'broken.pdf', { type: 'application/pdf' })
    fireEvent.change(inputs[0], { target: { files: [file] } })

    // Shown at the top of the tab AND on the Additional documents card, which
    // sits far below where the rejection used to scroll out of view.
    const shown = await screen.findAllByText('Could not read this PDF — the file appears to be corrupt or incomplete')
    expect(shown).toHaveLength(2)
  })

  it('asks before removing a document instead of deleting on one click', async () => {
    docs = [GONE_DOC]
    await openDocuments()
    await screen.findByText('File no longer available')
    fireEvent.click(screen.getAllByTitle('Remove')[0])
    // Nothing deleted yet — an inline confirm appeared.
    expect(deleteCalls).toEqual([])
    const bar = await screen.findByRole('alertdialog')
    fireEvent.click(within(bar).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(deleteCalls).toEqual([])

    fireEvent.click(screen.getAllByTitle('Remove')[0])
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(deleteCalls).toEqual(['doc-gone']))
  })

  it('creates a custom BOM from an inline name field (no native prompt)', async () => {
    docs = []
    await openDocuments()
    // The button expands into a form; nothing is created until it's submitted.
    fireEvent.click(await screen.findByRole('button', { name: 'New BOM' }))
    const input = screen.getByLabelText('Name this bill of materials')
    expect(manualCreates).toEqual([])
    fireEvent.change(input, { target: { value: 'Hydrants' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create BOM' }))
    await waitFor(() => expect(manualCreates).toEqual(['Hydrants']))
    // The new BOM opens straight into its editor.
    await screen.findByText('Edit materials')
  })

  it('saves BOM edits to the document the editor was opened for, even after the list reorders', async () => {
    // The editor is opened on a confirmed plan at index 0. A document is still
    // processing, so the 3s poll reloads the list — and a newer upload now
    // sits at index 0. Save used to PUT to "whatever is at docIdx" and wiped
    // that document's BOM.
    const PLAN = { ...GONE_DOC, id: 'doc-plan', name: 'Site Plan', fileMissing: false, hasFile: false, items: '1' }
    const PROC = { ...GONE_DOC, id: 'doc-proc', name: 'Older Upload', fileMissing: false, hasFile: false, items: '—', processing: true, status: 'Processing', statusTone: 'blue' }
    const NEW = { ...PROC, id: 'doc-new', name: 'Newer Upload' }
    docs = [PLAN, PROC]
    lineItems = {
      'doc-plan': [{ group: 'Water', count: 1, tone: 'blue', items: [{ n: '12" DI Pipe', q: '100 LF' }] }],
      'doc-new': [{ group: 'Other', count: 1, tone: 'gray', items: [{ n: 'SOMETHING ELSE', q: '1' }] }],
    }
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      await openDocuments()
      fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
      await screen.findByDisplayValue('12" DI Pipe')

      // The processing poll fires and the list comes back reordered.
      docs = [NEW, PLAN]
      vi.advanceTimersByTime(3100)
      await screen.findByText('Newer Upload')
      // The editor is still open on the plan's draft, and the plan is the
      // selected document (its card is highlighted), not the newcomer.
      const input = await screen.findByDisplayValue('12" DI Pipe')
      fireEvent.change(input, { target: { value: '12" DI Pipe, Class 350' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save' }))
      await waitFor(() => expect(savedTo).toEqual(['doc-plan']))
      expect(lineItems['doc-new'][0]).toMatchObject({ group: 'Other' }) // untouched
    } finally {
      vi.useRealTimers()
    }
  })
})
