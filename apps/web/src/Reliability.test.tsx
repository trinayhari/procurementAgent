// Flow-reliability regressions: destructive actions confirm inline, failed
// and mocked extractions are honest, the RFQ modal never drops edits or
// strands a failed send, sourcing says why it can't proceed, and awarding
// is a two-step commitment that remembers prior awards. Drives the real
// <App /> against a mocked fetch (see testUtils.tsx).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { describeApiError } from './api'
import { makeFetch, openProject, resetDom, json, PROJECT, USER } from './testUtils'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
beforeEach(() => { resetDom() })

// ------------------------------------------------------------- auth errors
describe('auth error formatting', () => {
  it('turns a Pydantic 422 detail list into readable text', () => {
    const body = { detail: [{ type: 'value_error', loc: ['body', 'email'], msg: 'value is not a valid email address: The part after the @-sign is reserved.' }] }
    expect(describeApiError(body, 'fallback')).toBe('Email: The part after the @-sign is reserved.')
    expect(describeApiError({ detail: 'Invalid email or password' }, 'fallback')).toBe('Invalid email or password')
    expect(describeApiError({}, 'fallback')).toBe('fallback')
    expect(describeApiError({ detail: [{}] }, 'fallback')).toBe('fallback')
  })
})

// ------------------------------------------------------ destructive actions
describe('destructive actions confirm inline', () => {
  it('deletes a project only after the inline confirmation, never via window.confirm', async () => {
    const calls: string[] = []
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === `/api/projects/${PROJECT.id}` && init && init.method === 'DELETE') { calls.push(path); return new Response(null, { status: 204 }) }
      return undefined
    }))
    await openProject()
    fireEvent.click(screen.getByTitle('Delete project'))
    // Nothing deleted yet — the confirm bar is showing instead.
    expect(calls).toHaveLength(0)
    expect(confirmSpy).not.toHaveBeenCalled()
    const bar = await screen.findByRole('alertdialog')
    expect(bar.textContent).toContain('permanently removes')
    fireEvent.click(within(bar).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(calls).toHaveLength(0)

    fireEvent.click(screen.getByTitle('Delete project'))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete project' }))
    await waitFor(() => expect(calls).toEqual([`/api/projects/${PROJECT.id}`]))
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('asks before removing a plan document and names what goes with it', async () => {
    const deletes: string[] = []
    const DOC = { id: 'doc-1', name: 'Site Plan.pdf', type: 'Site Plan', date: 'Sep 1, 2026', status: 'Analyzed', statusTone: 'success', items: '12', pages: 3, processing: false, hasFile: true, planType: 'site_plan', reviewed: true }
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === '/api/documents/plan-types') return json([{ key: 'site_plan', label: 'Site Plan', description: '', enabled: true, categories: ['Water'], singleton: true }])
      if (path.endsWith('/documents')) return json([DOC])
      if (path === '/api/documents/doc-1/line-items') return json([])
      if (path === '/api/documents/doc-1' && init && init.method === 'DELETE') { deletes.push(path); return new Response(null, { status: 204 }) }
      return undefined
    }))
    await openProject('documents')
    fireEvent.click(await screen.findByTitle('Remove'))
    const bar = await screen.findByRole('alertdialog')
    expect(bar.textContent).toContain('Site Plan.pdf')
    expect(bar.textContent).toContain('confirmed BOM')
    expect(deletes).toHaveLength(0)
    fireEvent.click(within(bar).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(deletes).toEqual(['/api/documents/doc-1']))
  })
})

// ------------------------------------------------------- inline creation
describe('naming a custom BOM / trade never uses window.prompt', () => {
  it('creates a custom BOM from an inline name field', async () => {
    const created: unknown[] = []
    const promptSpy = vi.fn(() => 'IGNORED')
    vi.stubGlobal('prompt', promptSpy)
    let docs: unknown[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/documents') && !(init && init.method)) return json(docs)
      if (path === '/api/documents/manual' && init && init.method === 'POST') {
        const body = JSON.parse(String(init.body)); created.push(body)
        const doc = { id: 'bom-1', name: body.name, type: 'Custom BOM', date: 'Sep 1, 2026', status: 'Draft', statusTone: 'gray', items: '0', pages: 0, processing: false, hasFile: false, planType: 'custom_bom' }
        docs = [doc]
        return json(doc, 201)
      }
      if (path === '/api/documents/bom-1/line-items') return json([])
      return undefined
    }))
    await openProject('documents')
    fireEvent.click(await screen.findByRole('button', { name: /New BOM/ }))
    const field = await screen.findByPlaceholderText('Name this bill of materials')
    fireEvent.change(field, { target: { value: 'Yard drainage extras' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create BOM' }))
    await waitFor(() => expect(created).toEqual([{ name: 'Yard drainage extras', projectId: PROJECT.id }]))
    expect(promptSpy).not.toHaveBeenCalled()
    // Lands in the editor for the new BOM.
    await screen.findByText('Edit materials')
  })

  it('asks before replacing a plan whose BOM was already confirmed', async () => {
    const DOC = { id: 'doc-1', name: 'Site Plan.pdf', type: 'Site Plan', date: 'Sep 1, 2026', status: 'Analyzed', statusTone: 'success', items: '12', pages: 3, processing: false, hasFile: true, planType: 'site_plan', reviewed: true }
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === '/api/documents/plan-types') return json([{ key: 'site_plan', label: 'Site Plan', description: '', enabled: true, categories: ['Water'], singleton: true }])
      if (path.endsWith('/documents')) return json([DOC])
      if (path === '/api/documents/doc-1/line-items') return json([])
      return undefined
    }))
    await openProject('documents')
    fireEvent.click(await screen.findByRole('button', { name: 'Replace' }))
    const bar = await screen.findByRole('alertdialog')
    expect(bar.textContent).toContain('confirmed BOM is discarded')
    fireEvent.click(within(bar).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })
})

// --------------------------------------------------------- extraction state
describe('extracted-materials panel is honest about document state', () => {
  const FAILED = { id: 'doc-f', name: 'Electrical.pdf', type: 'Electrical Plan', date: 'Sep 1, 2026', status: 'Failed', statusTone: 'danger', items: '—', pages: 2, processing: false, hasFile: true, planType: 'electrical_plan', error: 'Extraction failed: model timeout', mocked: false }
  const DEMO_GROUPS = [{ group: 'Water Materials', count: 1, tone: 'blue', items: [{ n: 'DEMO 12" DI Pipe', q: '2,400 LF' }] }]

  it('shows the failure reason with a retry, and never the project-wide demo BOM', async () => {
    const analyzed: string[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/documents')) return json([FAILED])
      // The project-level feed returns the shared demo BOM for every project —
      // it must not be rendered as this document's materials.
      if (path === `/api/projects/${PROJECT.id}/line-items`) return json(DEMO_GROUPS)
      if (path === '/api/documents/doc-f/line-items') return json(DEMO_GROUPS)
      if (path === '/api/documents/doc-f/analyze' && init && init.method === 'POST') { analyzed.push(path); return json({ ...FAILED, status: 'Processing', processing: true, error: null }) }
      return undefined
    }))
    await openProject('documents')
    await screen.findByText(/Extraction failed — no materials were read/)
    expect(screen.getByText('Extraction failed: model timeout')).toBeTruthy()
    expect(screen.queryByText('DEMO 12" DI Pipe')).toBeNull()
    expect(screen.queryByRole('button', { name: /Confirm BOM/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
    expect(screen.getByText('Analysis failed')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Retry analysis/ }))
    await waitFor(() => expect(analyzed).toEqual(['/api/documents/doc-f/analyze']))
  })

  it('labels a mocked extraction as sample items not read from the document', async () => {
    const MOCKED = { ...FAILED, id: 'doc-m', name: 'Site.pdf', status: 'Analyzed', statusTone: 'success', items: '3', error: null, mocked: true, summary: 'Mock extraction.' }
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/documents')) return json([MOCKED])
      if (path === '/api/documents/doc-m/line-items') return json([{ group: 'Water', count: 1, tone: 'blue', items: [{ n: 'Example pipe', q: '—' }] }])
      return undefined
    }))
    await openProject('documents')
    await screen.findByText('Example pipe')
    expect(screen.getByText(/No AI key is configured, so these are example items/)).toBeTruthy()
    expect(screen.getAllByText('Sample extraction').length).toBeGreaterThan(0)
    expect(screen.queryByText(/AI detected/)).toBeNull()
  })

  it('blocks switching documents while a BOM edit is open', async () => {
    const A = { ...FAILED, id: 'doc-a', name: 'Plan A.pdf', status: 'Analyzed', statusTone: 'success', items: '1', error: null, planType: 'other' }
    const B = { ...A, id: 'doc-b', name: 'Plan B.pdf' }
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/documents')) return json([A, B])
      if (path === '/api/documents/doc-a/line-items') return json([{ group: 'Water', count: 1, tone: 'blue', items: [{ n: 'Item from A', q: '1 EA' }] }])
      if (path === '/api/documents/doc-b/line-items') return json([{ group: 'Water', count: 1, tone: 'blue', items: [{ n: 'Item from B', q: '1 EA' }] }])
      return undefined
    }))
    await openProject('documents')
    await screen.findByText('Item from A')
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    await screen.findByDisplayValue('Item from A')
    fireEvent.click(screen.getByText('Plan B.pdf'))
    await screen.findByText('Save or cancel your BOM edits before switching documents.')
    // Still editing A — B's items were not loaded into the editor.
    expect(screen.getByDisplayValue('Item from A')).toBeTruthy()
    expect(screen.queryByText('Item from B')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    fireEvent.click(screen.getByText('Plan B.pdf'))
    await screen.findByText('Item from B')
  })
})

// ---------------------------------------------------------------- RFQ modal
const RFQ_BASE = {
  id: 'rfq-1', projectId: PROJECT.id, package: 'water', pkg: 'Water Utilities', sup: '', folder: '', preview: '', time: '',
  logo: 'WU', logoBg: '#334155', kind: 'materials', attachments: [], lineItems: [{ n: '12" DI Pipe', q: '100 LF' }],
  subject: 'RFQ: Water Utilities — Riverside Yard', body: 'Please quote.',
}

describe('RFQ modal', () => {
  it('offers Retry for a partially failed send, showing each recipient\'s state and reason', async () => {
    const sends: string[] = []
    let status = 'Send failed'
    const FAILED_RFQ = {
      ...RFQ_BASE, status: 'Send failed', statusTone: 'danger',
      recipients: [
        { supplierId: 's1', name: 'Core & Main', email: 'a@x.com', sendStatus: 'sent', sentMessageId: 'm1' },
        { supplierId: 's2', name: 'Ferguson', email: 'b@x.com', sendStatus: 'failed', sendError: 'Gmail: 550 mailbox unavailable' },
      ],
    }
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/rfqs/generated')) return json([FAILED_RFQ])
      if (path.endsWith('/conversation')) return json({ rfqId: 'rfq-1', status, statusTone: 'danger', gmail: false, thread: [] })
      if (path.endsWith('/rfqs/rfq-1/send') && init && init.method === 'POST') {
        sends.push(path); status = 'Awaiting'
        return json({ ...FAILED_RFQ, status: 'Awaiting', statusTone: 'warn', recipients: FAILED_RFQ.recipients.map((r) => ({ ...r, sendStatus: 'sent', sendError: null })) })
      }
      return undefined
    }))
    await openProject('rfqs')
    // The rail has a folder for failed sends.
    await screen.findByText('Send failed')
    fireEvent.click(await screen.findByText(FAILED_RFQ.subject))
    await screen.findByText(/Delivery failed/)
    expect(screen.getByText('Gmail: 550 mailbox unavailable')).toBeTruthy()
    const modal = screen.getByText(/Delivery failed/).closest('[style*="position: relative"]') as HTMLElement
    expect(within(modal).getByText('Sent')).toBeTruthy()
    expect(within(modal).getByText('Failed')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Retry send \(1\)/ }))
    // Two-step: the confirm names the unsent count, then retries.
    const bar = await screen.findByRole('alertdialog')
    expect(bar.textContent).toContain('1 supplier')
    fireEvent.click(within(bar).getByRole('button', { name: 'Retry now' }))
    await waitFor(() => expect(sends).toHaveLength(1))
    await screen.findByText('Awaiting')
    expect(screen.queryByRole('button', { name: /Retry send/ })).toBeNull()
  })

  it('saves a draft, guards unsaved edits on close, and disables Send with a reason when there are no recipients', async () => {
    const saves: unknown[] = []
    const DRAFT = { ...RFQ_BASE, status: 'Draft', statusTone: 'gray', recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com' }] }
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/rfqs/generated')) return json([DRAFT])
      if (path.endsWith('/rfqs/rfq-1') && init && init.method === 'PUT') { saves.push(JSON.parse(String(init.body))); return json(DRAFT) }
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(DRAFT.subject))
    await screen.findByText(/Review RFQ draft/)
    const save = screen.getByRole('button', { name: 'Save draft' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)

    fireEvent.change(screen.getByDisplayValue(DRAFT.subject), { target: { value: 'RFQ rev A' } })
    expect(save.disabled).toBe(false)
    // Closing with unsaved edits asks first instead of dropping them.
    fireEvent.click(screen.getByTitle('Close'))
    const guard = await screen.findByRole('alertdialog')
    expect(guard.textContent).toContain('unsaved changes')
    fireEvent.click(within(guard).getByRole('button', { name: 'Cancel' }))
    expect(screen.getByDisplayValue('RFQ rev A')).toBeTruthy()

    fireEvent.click(save)
    await screen.findByText('Draft saved.')
    expect(saves).toHaveLength(1)
    expect((saves[0] as { subject: string }).subject).toBe('RFQ rev A')
    expect(save.disabled).toBe(true)

    // Drop the only recipient: Send is disabled and the footer says why.
    fireEvent.click(screen.getByTitle('Remove recipient'))
    const send = screen.getByRole('button', { name: /Send RFQ \(0\)/ }) as HTMLButtonElement
    expect(send.disabled).toBe(true)
    expect(screen.getByText(/Add at least one supplier with an email address/)).toBeTruthy()
    expect(screen.getByText('Nothing can be sent without a recipient.')).toBeTruthy()
  })
})

// ------------------------------------------------------------- sourcing
describe('supplier search says why it cannot proceed', () => {
  it('surfaces items pending BOM review instead of "no items found", and disables Generate with the reason', async () => {
    const TIERS = [{ tier: 1, label: 'Local · 0–25 mi', suppliers: [{ id: 'f1', name: 'Core & Main', address: '1 Main St', distanceMiles: 5, tier: 1, email: 'a@x.com', phone: '', website: '', materialCategories: [], emailSource: 'mock', relevanceScore: 1, verifyReason: '' }] }]
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.includes('/packages/water/bom')) return json({ package: 'water', label: 'Water Utilities', tone: 'blue', count: 0, items: [], seeded: false, custom: false, pendingReview: 2 })
      if (path.includes('/suppliers/found')) return json({ status: 'done', mocked: true, radiusMi: 75, package: 'water', error: null, tiers: TIERS })
      return undefined
    }))
    await openProject('suppliers')
    await screen.findByText(/2 documents have Water Utilities items awaiting your review/)
    expect(screen.queryByText(/No Water Utilities items found yet/)).toBeNull()
    fireEvent.click(await screen.findByTitle('Select for RFQ'))
    const gen = await screen.findByRole('button', { name: /Generate RFQ draft/ }) as HTMLButtonElement
    expect(gen.disabled).toBe(true)
    expect(screen.getByText('Confirm the extracted BOM on 2 documents first')).toBeTruthy()
    // The notice links straight to the review step.
    fireEvent.click(screen.getByRole('button', { name: /Review in Documents/ }))
    await waitFor(() => expect(window.location.hash).toBe(`#/project/${PROJECT.id}/documents`))
  })

  it('reports a failed search rather than "no suppliers found"', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.includes('/suppliers/found')) return json({ status: 'error', mocked: false, radiusMi: 75, package: 'water', error: 'Geocoding failed for the project address', tiers: [] })
      return undefined
    }))
    await openProject('suppliers')
    await screen.findByText(/Search failed: Geocoding failed for the project address/)
  })
})

// ----------------------------------------------------------------- award
describe('award is a confirmed commitment that remembers prior awards', () => {
  const LC = {
    pkg: 'Water Utilities', package: 'water', budget: 200000,
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
  const QUOTES = [{ id: 'q1', sup: 'Core & Main', pkg: 'Water Utilities', amount: '$10,000', freight: '$500', total: '$10,500', lead: '10 days', date: 'Sep 1', logo: 'CM', logoBg: '#111', best: true }]

  it('confirms before awarding, then flags the package as already awarded', async () => {
    const awards: unknown[] = []
    let decisions: unknown[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/quotes')) return json(QUOTES)
      if (path.includes('/line-comparison')) return json(LC)
      if (path.endsWith('/purchase-decisions')) return json(decisions)
      if (path.endsWith('/award') && init && init.method === 'POST') {
        awards.push(JSON.parse(String(init.body)))
        decisions = [{ id: 'pd-1', projectId: PROJECT.id, package: 'water', packageLabel: 'Water Utilities', strategy: 'mix', selections: {}, supplierIds: ['s1'], suppliers: ['Core & Main'], total: 10500, material: 10000, freight: 500, leadDays: 10, poCount: 1, decidedBy: USER.id, decidedByEmail: USER.email, createdAt: '2026-09-17T10:00:00' }]
        return json({ status: 'awarded', message: 'Awarded Water Utilities for $10,500 — 1 PO to Core & Main.', total: 10500, material: 10000, freight: 500, leadDays: 10, suppliers: ['Core & Main'], poCount: 1 })
      }
      return undefined
    }))
    await openProject('quotes')
    fireEvent.click(await screen.findByRole('button', { name: 'Compare' }))
    await screen.findByText(/Quote Comparison/)
    expect(screen.queryByText(/Already awarded/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /Submit award · issue 1 PO/ }))
    expect(awards).toHaveLength(0)
    const bar = await screen.findByRole('alertdialog')
    expect(bar.textContent).toContain('$10,500')
    expect(bar.textContent).toContain('Core & Main')
    expect(bar.textContent).toContain('notify 1 other supplier')
    expect(bar.textContent).toContain('can’t be recalled')
    fireEvent.click(within(bar).getByRole('button', { name: 'Confirm award' }))
    await waitFor(() => expect(awards).toHaveLength(1))
    expect((awards[0] as { strategy: string }).strategy).toBe('mix')

    await screen.findByText(/Already awarded/)
    expect(screen.getByText(/by pm@acmebuild.com/)).toBeTruthy()
    // A second submission is possible but is labelled as a re-award and
    // warns that suppliers are emailed again.
    fireEvent.click(screen.getByRole('button', { name: /Award again/ }))
    const again = await screen.findByRole('alertdialog')
    expect(again.textContent).toContain('already awarded')
    expect(within(again).getByRole('button', { name: 'Award again' })).toBeTruthy()
  })

  it('round-trips a package label with spaces through the compare URL', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/quotes')) return json(QUOTES)
      if (path.includes('/line-comparison')) return json(LC)
      return undefined
    }))
    await openProject('quotes')
    fireEvent.click(await screen.findByRole('button', { name: 'Compare' }))
    await screen.findByText(/Quote Comparison/)
    expect(window.location.hash).toBe(`#/project/${PROJECT.id}/quotes/compare/Water%20Utilities`)
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    const calls = fetchMock.mock.calls.map((c) => String(c[0])).filter((u) => u.includes('line-comparison'))
    expect(calls.every((u) => u.endsWith('/packages/Water%20Utilities/line-comparison'))).toBe(true)
  })
})
