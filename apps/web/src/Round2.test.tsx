// Round-2 reliability regressions (BUG-38 … BUG-43 + residuals): one request
// per confirmed action no matter how fast the clicks, an "already sent" after
// our own send is not a failure, deleting the open draft closes its modal,
// unsaved RFQ edits block in-app navigation, no hard-coded comparison fetch,
// invite revoke confirms (Escape dismisses) and mock-mode invites hand back a
// link, and the est. value field takes only amounts. Drives the real <App />
// against a mocked fetch (see testUtils.tsx).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup, within, act } from '@testing-library/react'
import { makeFetch, openProject, resetDom, json, PROJECT, USER } from './testUtils'
import { loadModelData } from './api'
import { isMoneyLike } from './App'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
beforeEach(() => { resetDom() })

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
const QUOTES = [{ id: 'q1', sup: 'Core & Main', pkg: 'Water Utilities', package: 'water', amount: '$10,000', freight: '$500', total: '$10,500', lead: '10 days', date: 'Sep 1', logo: 'CM', logoBg: '#111', best: true }]
const AWARDED = { status: 'awarded', message: 'Awarded Water Utilities for $10,500 — 1 PO to Core & Main.', total: 10500, material: 10000, freight: 500, leadDays: 10, suppliers: ['Core & Main'], poCount: 1 }

const RFQ_BASE = {
  id: 'rfq-1', projectId: PROJECT.id, package: 'water', pkg: 'Water Utilities', sup: '', folder: '', preview: '', time: '',
  logo: 'WU', logoBg: '#334155', kind: 'materials', attachments: [], lineItems: [{ n: '12" DI Pipe', q: '100 LF' }],
  subject: 'RFQ: Water Utilities — Riverside Yard', body: 'Please quote.',
}
const DRAFT = { ...RFQ_BASE, status: 'Draft', statusTone: 'gray', recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com' }] }
const SENT = { ...DRAFT, status: 'Awaiting', statusTone: 'warn', recipients: [{ ...DRAFT.recipients[0], sendStatus: 'sent', sentMessageId: 'm1' }] }

// Click an element N times inside ONE task, bypassing testing-library's act()
// (which flushes React between clicks and would hide the race): this is what
// a driver's `el.click(); el.click(); el.click()` does, and what the tester
// reproduced — React's "disabled" re-render lands only after the task ends.
function rapidClicks(el: Element, n: number) {
  for (let i = 0; i < n; i++) el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
}

// Hold a response until released, to keep a request "in flight".
function gate() {
  let release!: () => void
  const p = new Promise<void>((r) => { release = r })
  return { p, release }
}

// ------------------------------------------------------------------ BUG-38
describe('award confirm is one-shot', () => {
  it('fires a single POST /award for a rapid triple-click on Confirm award', async () => {
    const awards: unknown[] = []
    const g = gate()
    vi.stubGlobal('fetch', makeFetch(async (path, init) => {
      if (path.endsWith('/quotes')) return json(QUOTES)
      if (path.includes('/line-comparison')) return json(LC)
      if (path.endsWith('/award') && init && init.method === 'POST') { awards.push(JSON.parse(String(init.body))); await g.p; return json(AWARDED) }
      return undefined
    }))
    await openProject('quotes')
    fireEvent.click(await screen.findByRole('button', { name: 'Compare' }))
    fireEvent.click(await screen.findByRole('button', { name: /Submit award · issue 1 PO/ }))
    const confirm = within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Confirm award' })
    // Three clicks in the same task — faster than React can re-render the
    // button as disabled.
    rapidClicks(confirm, 3)
    await new Promise((r) => setTimeout(r, 30))
    expect(awards).toHaveLength(1)
    await act(async () => { g.release() })
    await screen.findByText(/Awarded Water Utilities/)
    expect(awards).toHaveLength(1)
  })
})

// ------------------------------------------------------------------ BUG-43
describe('RFQ send is one-shot', () => {
  it('fires a single POST /send for a rapid triple-click on Send now', async () => {
    const sends: string[] = []
    const g = gate()
    vi.stubGlobal('fetch', makeFetch(async (path, init) => {
      if (path.endsWith('/rfqs/generated')) return json([DRAFT])
      if (path.endsWith('/rfqs/rfq-1') && init && init.method === 'PUT') return json(DRAFT)
      if (path.endsWith('/rfqs/rfq-1/send') && init && init.method === 'POST') { sends.push(path); await g.p; return json(SENT) }
      if (path.includes('/conversation')) return json({ rfqId: 'rfq-1', status: 'Awaiting', statusTone: 'warn', gmail: false, thread: [] })
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(DRAFT.subject))
    fireEvent.click(await screen.findByRole('button', { name: /Send RFQ \(1\)/ }))
    const now = within(await screen.findByRole('alertdialog')).getByRole('button', { name: /Send now/ })
    rapidClicks(now, 3)
    await waitFor(() => expect(sends).toHaveLength(1))
    await new Promise((r) => setTimeout(r, 30))
    expect(sends).toHaveLength(1)
    await act(async () => { g.release() })
    await waitFor(() => expect(screen.getAllByText('Awaiting').length).toBeGreaterThan(0))
    // ('Send failed' also names a folder in the list — look for the error copy.)
    expect(screen.queryByText(/Send failed[ .—]/)).toBeNull()
  })

  it('does not report "already sent" as a failure right after its own successful send', async () => {
    let sent = 0
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/rfqs/generated')) return json([DRAFT])
      if (path.endsWith('/rfqs/rfq-1') && init && init.method === 'PUT') return json(DRAFT)
      if (path.endsWith('/rfqs/rfq-1/send') && init && init.method === 'POST') {
        sent++
        return sent === 1 ? json(SENT) : json({ detail: 'RFQ was already sent (status: Awaiting)' }, 409)
      }
      if (path.includes('/conversation')) return json({ rfqId: 'rfq-1', status: 'Awaiting', statusTone: 'warn', gmail: false, thread: [] })
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(DRAFT.subject))
    fireEvent.click(await screen.findByRole('button', { name: /Send RFQ \(1\)/ }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: /Send now/ }))
    await waitFor(() => expect(sent).toBe(1))
    // A replayed send (e.g. a stale second tab) is refused by the backend —
    // the modal treats that as confirmation, not as a failed send.
    const modalSend = screen.queryByRole('button', { name: /Send now|Retry/ })
    if (modalSend) fireEvent.click(modalSend)
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryByText(/Send failed[ .—]/)).toBeNull()
    expect(screen.queryByText(/already sent/)).toBeNull()
  })
})

// ------------------------------------------------------------------ BUG-41
describe('deleting the draft that is open', () => {
  it('closes the review modal when its draft is deleted from the list', async () => {
    let rfqs: object[] = [DRAFT]
    const deletes: string[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/rfqs/generated')) return json(rfqs)
      if (path.endsWith('/rfqs/rfq-1') && init && init.method === 'DELETE') { deletes.push(path); rfqs = []; return new Response(null, { status: 204 }) }
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(DRAFT.subject))
    await screen.findByText(/Review RFQ draft/)
    // The list's delete control is still reachable programmatically (a
    // driver, or a keyboard user tabbing behind the backdrop).
    fireEvent.click(screen.getByTitle('Delete draft'))
    const bar = await screen.findByRole('alertdialog')
    const confirm = within(bar).getByRole('button', { name: 'Delete draft' })
    rapidClicks(confirm, 2) // double-click: one DELETE
    await waitFor(() => expect(deletes).toHaveLength(1))
    await waitFor(() => expect(screen.queryByText(/Review RFQ draft/)).toBeNull())
    expect(deletes).toHaveLength(1)
  })
})

// ------------------------------------------------------------------ BUG-40
describe('unsaved RFQ edits block in-app navigation', () => {
  it('keeps the modal and asks to discard when the sidebar or a tab is clicked', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/rfqs/generated')) return json([DRAFT])
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(DRAFT.subject))
    await screen.findByText(/Review RFQ draft/)
    fireEvent.change(screen.getByDisplayValue(DRAFT.subject), { target: { value: 'RFQ rev B' } })

    fireEvent.click(screen.getAllByRole('button', { name: /Dashboard/ })[0])
    const guard = await screen.findByRole('alertdialog')
    expect(guard.textContent).toContain('unsaved changes')
    expect(window.location.hash).toBe(`#/project/${PROJECT.id}/rfqs`)
    expect(screen.getByDisplayValue('RFQ rev B')).toBeTruthy()
    fireEvent.click(within(guard).getByRole('button', { name: 'Cancel' }))

    // Browser Back / a hand-edited URL is refused the same way.
    window.location.hash = `#/project/${PROJECT.id}/overview`
    await waitFor(() => expect(screen.getByRole('alertdialog')).toBeTruthy())
    await waitFor(() => expect(window.location.hash).toBe(`#/project/${PROJECT.id}/rfqs`))
    expect(screen.getByDisplayValue('RFQ rev B')).toBeTruthy()
  })
})

// ------------------------------------------------------------------ BUG-42
describe('workspace bundle', () => {
  it('no longer requests a hard-coded package comparison', async () => {
    const paths: string[] = []
    vi.stubGlobal('fetch', makeFetch((path) => { paths.push(path); return undefined }))
    localStorage.setItem('procureai_token', 'tok')
    await loadModelData(PROJECT.id)
    expect(paths.some((p) => p.includes('/comparison'))).toBe(false)
    expect(paths.some((p) => p.endsWith(`/api/projects/${PROJECT.id}/documents`))).toBe(true)
  })
})

// ------------------------------------------------------------ BUG-39 / 30
describe('team invites', () => {
  const INVITE = { id: 'inv-1', email: 'newbie@example.com', status: 'pending', invitedByUserId: USER.id, createdAt: null, expiresAt: null, acceptedAt: null, emailed: false, acceptUrl: 'http://localhost:5250/#/invite/tok-123' }

  async function openSettings() {
    await openProject()
    fireEvent.click(screen.getAllByRole('button', { name: /Settings/ })[0])
    await screen.findByText('Team')
  }

  it('revokes only after an inline confirm, which Escape dismisses, and never double-fires', async () => {
    const deletes: string[] = []
    let invites: object[] = [INVITE]
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === '/api/team') return json({ members: [USER], invites })
      if (path === '/api/team/invites/inv-1' && init && init.method === 'DELETE') { deletes.push(path); invites = []; return new Response(null, { status: 204 }) }
      return undefined
    }))
    await openSettings()
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke' }))
    expect(deletes).toHaveLength(0)
    await screen.findByRole('alertdialog')
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(deletes).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Revoke' }))
    const confirm = within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Revoke' })
    rapidClicks(confirm, 2)
    await waitFor(() => expect(deletes).toHaveLength(1))
    await waitFor(() => expect(screen.queryByText('newbie@example.com')).toBeNull())
    expect(deletes).toHaveLength(1)
  })

  it('in mock mode says the email was not delivered and offers the link + resend', async () => {
    const resends: string[] = []
    const written: string[] = []
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: async (t: string) => { written.push(t) } } })
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === '/api/team') return json({ members: [USER], invites: [INVITE] })
      if (path === '/api/team/invites' && init && init.method === 'POST') return json(INVITE, 201)
      if (path === '/api/team/invites/inv-1/resend' && init && init.method === 'POST') { resends.push(path); return json(INVITE) }
      return undefined
    }))
    await openSettings()
    fireEvent.change(screen.getByPlaceholderText(/teammate@/i), { target: { value: 'newbie@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: /Invite/ }))
    await screen.findByText(/nothing was delivered/)
    expect(screen.queryByText(/Invitation sent to/)).toBeNull()

    fireEvent.click(await screen.findByRole('button', { name: 'Copy invite link' }))
    await waitFor(() => expect(written).toEqual([INVITE.acceptUrl]))
    await screen.findByText('Copied ✓')
    fireEvent.click(screen.getByRole('button', { name: 'Resend' }))
    await waitFor(() => expect(resends).toHaveLength(1))
    await screen.findByText(/copy the invite link/)
  })
})

// ------------------------------------------------------------ BUG-27 residual
describe('project est. value', () => {
  it('accepts amounts only', () => {
    for (const ok of ['', '$4.2M', '450,000', '1.5 b', '12000.50', '$3k']) expect(isMoneyLike(ok)).toBe(true)
    for (const bad of ['abc', '$', '4.2.3', 'twelve', '1,00']) expect(isMoneyLike(bad)).toBe(false)
  })

  it('blocks creating a project with a non-amount value and says why', async () => {
    const posts: unknown[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === '/api/projects' && init && init.method === 'POST') { posts.push(JSON.parse(String(init.body))); return json({ ...PROJECT, id: 'p-new' }, 201) }
      return undefined
    }))
    await openProject()
    fireEvent.click(screen.getAllByRole('button', { name: /Projects/ })[0])
    fireEvent.click(await screen.findByRole('button', { name: /New project/ }))
    fireEvent.change(screen.getByPlaceholderText(/Riverside Water/), { target: { value: 'Val Test' } })
    fireEvent.change(screen.getByPlaceholderText('$0'), { target: { value: 'abc' } })
    await screen.findByText(/Enter an amount/)
    fireEvent.click(screen.getByRole('button', { name: /Create project/ }))
    await new Promise((r) => setTimeout(r, 20))
    expect(posts).toHaveLength(0)
    fireEvent.change(screen.getByPlaceholderText('$0'), { target: { value: '$4.2M' } })
    expect(screen.queryByText(/Enter an amount/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Create project/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
  })
})
