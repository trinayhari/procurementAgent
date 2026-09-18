// Email-workflow UI truthfulness: Settings names the missing Gmail variables
// and the last Gmail / AI error, the connection check is explicit (never on
// load), an RFQ conversation says when the live Gmail read failed instead of
// passing off the stored copy as live, an undelivered RFQ is not "Sent", team
// invites surface a failed send with the link, and the Quotes table flags a
// reply that had no amount. Drives the real <App /> against a mocked fetch.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { makeFetch, openProject, resetDom, json, PROJECT, USER } from './testUtils'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
beforeEach(() => { resetDom() })

const CFG_BASE = {
  configured: true, mocked: false, senderAddressSet: true, fromAddress: 'bids@ws.com',
  fromHeader: 'Pat Mason — Acme Build Co. <bids@ws.com>', ccEmail: null, missing: [],
  gmail: { lastError: null, lastErrorAt: null, lastOkAt: null },
  llm: { configured: true, model: 'gpt-4.1', baseUrl: null, lastError: null, lastErrorAt: null, lastErrorWhere: null, lastOkAt: null },
}

async function openSettings() {
  await openProject()
  fireEvent.click(screen.getAllByRole('button', { name: /Settings/ })[0])
  await screen.findByText('Email delivery')
}

describe('Settings → email delivery', () => {
  it('names the missing PROCUREAI_GMAIL_* variables when not configured', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === '/api/auth/email-config') return json({ ...CFG_BASE, configured: false, mocked: true, senderAddressSet: false, fromAddress: 'rfq@procureai.local', missing: ['PROCUREAI_GMAIL_REFRESH_TOKEN', 'PROCUREAI_GMAIL_SENDER_ADDRESS'], llm: { ...CFG_BASE.llm, configured: false } })
      return undefined
    }))
    await openSettings()
    await screen.findByText('Not configured')
    expect(screen.getByText(/PROCUREAI_GMAIL_REFRESH_TOKEN, PROCUREAI_GMAIL_SENDER_ADDRESS/)).toBeTruthy()
    expect(screen.getByText(/No AI key set/)).toBeTruthy()
  })

  it('shows the last Gmail failure and the AI parser outage, and checks connections only on click', async () => {
    const probes: string[] = []
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === '/api/auth/email-config') return json({
        ...CFG_BASE,
        gmail: { lastError: 'Gmail connection expired or was revoked (invalid_grant) — re-mint the refresh token (docs/email-setup.md, Step 3) and restart the backend.', lastErrorAt: '2026-09-17T10:00:00Z', lastOkAt: null },
        llm: { ...CFG_BASE.llm, lastError: 'LLM rejected the API key (401) — an OpenAI sk-proj key is paired with the OpenRouter base URL; use an sk-or-… key or clear PROCUREAI_OPENAI_BASE_URL.', lastErrorWhere: 'quote parser' },
      })
      if (path === '/api/health/providers') {
        probes.push(path)
        return json({ ok: false, gmail: { ok: false, error: 'Gmail connection expired or was revoked (invalid_grant) — re-mint the refresh token (docs/email-setup.md, Step 3) and restart the backend.', emailAddress: null, senderAddress: 'bids@ws.com', senderAddressMatches: null, sendScope: false, readScope: false }, llm: { ok: true, error: null, model: 'gpt-4.1' } })
      }
      return undefined
    }))
    await openSettings()
    await screen.findByText(/Gmail is configured but the last call failed: Gmail connection expired/)
    expect(screen.getByText(/AI parsing unavailable — LLM rejected the API key \(401\)/)).toBeTruthy()
    // Nothing probed on load.
    expect(probes).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Check connections' }))
    await screen.findByText(/^Gmail: Gmail connection expired/)
    await screen.findByText(/AI model: gpt-4.1 answered/)
    expect(probes).toHaveLength(1)
  })
})

const RFQ_BASE = {
  id: 'rfq-1', projectId: PROJECT.id, package: 'water', pkg: 'Water Utilities', sup: '', folder: '', preview: '', time: '',
  logo: 'WU', logoBg: '#334155', kind: 'materials', attachments: [], lineItems: [{ n: '12" DI Pipe', q: '100 LF' }],
  subject: 'RFQ: Water Utilities — Riverside Yard', body: 'Please quote.',
}

describe('RFQ conversation', () => {
  it('says the live Gmail read failed and shows the stored copy, never as if live', async () => {
    const SENT = { ...RFQ_BASE, status: 'Awaiting', statusTone: 'warn', recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com', sendStatus: 'sent', sentMessageId: 'gm-1', threadId: 'thr-1' }] }
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/rfqs/generated')) return json([SENT])
      if (path.endsWith('/conversation')) return json({
        rfqId: 'rfq-1', status: 'Awaiting', statusTone: 'warn', gmail: false, configured: true,
        readError: 'Gmail is rate limiting this mailbox (HTTP 429) — wait a few minutes and retry.',
        thread: [{ dir: 'out', who: 'You · Proq', initials: 'YOU', time: 'Sent', subject: SENT.subject, body: SENT.body, attach: null, logoBg: null }],
      })
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(SENT.subject))
    await screen.findByText(/Couldn’t read the live Gmail thread — Gmail is rate limiting this mailbox \(HTTP 429\)/)
    expect(screen.queryByText(/set Gmail credentials/)).toBeNull()
  })

  it('labels an undelivered RFQ "Not delivered" in the stored thread', async () => {
    const FAILED = { ...RFQ_BASE, status: 'Send failed', statusTone: 'danger', recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com', sendStatus: 'failed', sendError: 'Gmail connection expired or was revoked (invalid_grant) — re-mint the refresh token (docs/email-setup.md, Step 3) and restart the backend.' }] }
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/rfqs/generated')) return json([FAILED])
      if (path.endsWith('/conversation')) return json({
        rfqId: 'rfq-1', status: 'Send failed', statusTone: 'danger', gmail: false, configured: true, readError: null,
        thread: [{ dir: 'out', who: 'You · Proq', initials: 'YOU', time: 'Not delivered', subject: FAILED.subject, body: FAILED.body, attach: null, logoBg: null }],
      })
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(FAILED.subject))
    await screen.findByText('Not delivered')
    expect(screen.getByText(/invalid_grant/)).toBeTruthy()
    await screen.findByText(/No live Gmail thread for this RFQ yet/)
  })
})

describe('project overview', () => {
  it('does not count a Send-failed RFQ as sent', async () => {
    const FAILED = { ...RFQ_BASE, status: 'Send failed', statusTone: 'danger', recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com', sendStatus: 'failed', sendError: 'boom' }] }
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/rfqs/generated')) return json([FAILED])
      return undefined
    }))
    await openProject()
    await screen.findByText(/1 RFQ failed to send — open it and retry/)
    expect(screen.queryByText(/1 sent/)).toBeNull()
  })
})

describe('team invites with a configured but failing mailbox', () => {
  it('shows the send error, offers the link, and the roster reflects the real outcome', async () => {
    const INVITE = { id: 'inv-1', email: 'newbie@example.com', status: 'pending', invitedByUserId: USER.id, createdAt: null, expiresAt: null, acceptedAt: null, emailed: false, emailedAt: null, emailError: 'Gmail is rate limiting this mailbox (HTTP 429) — wait a few minutes and retry.', acceptUrl: 'http://localhost:5250/#/invite/tok-123' }
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === '/api/team') return json({ members: [USER], invites: [INVITE] })
      if (path === '/api/team/invites' && init && init.method === 'POST') return json(INVITE, 201)
      return undefined
    }))
    await openProject()
    fireEvent.click(screen.getAllByRole('button', { name: /Settings/ })[0])
    await screen.findByText('Team')
    await screen.findByText(/Invitation pending — email failed: Gmail is rate limiting/)
    expect(screen.getByRole('button', { name: 'Copy invite link' })).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText(/teammate@/i), { target: { value: 'newbie@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: /Invite/ }))
    await screen.findByText(/but the email could not be sent: Gmail is rate limiting/)
    expect(screen.queryByText(/Email isn’t configured/)).toBeNull()
  })
})

describe('Quotes table', () => {
  it('flags a reply that had no readable amount as Needs review', async () => {
    const QUOTES = [
      { id: 'q1', sup: 'Core & Main', pkg: 'Water Utilities', package: 'water', amount: '$10,000', freight: '$500', total: '$10,500', lead: '10 days', date: 'Sep 1', logo: 'CM', logoBg: '#111', best: true, status: 'received' },
      { id: 'q2', sup: 'Ferguson', pkg: 'Water Utilities', package: 'water', amount: '—', freight: '—', total: '—', lead: '—', date: 'Sep 2', logo: 'FW', logoBg: '#222', best: false, status: 'needs_review' },
    ]
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/quotes')) return json(QUOTES)
      return undefined
    }))
    await openProject('quotes')
    const badge = await screen.findByText('Needs review')
    const row = badge.closest('[style*="display: grid"], [style*="display: flex"]') as HTMLElement
    expect(within(row).getByText('Ferguson')).toBeTruthy()
    await waitFor(() => expect(screen.getAllByText('Needs review')).toHaveLength(1))
  })
})

describe('award notifications', () => {
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
  const QUOTES = [{ id: 'q1', sup: 'Core & Main', pkg: 'Water Utilities', package: 'water', amount: '$10,000', freight: '$500', total: '$10,500', lead: '10 days', date: 'Sep 1', logo: 'CM', logoBg: '#111', best: true, status: 'received' }]
  const FAILED = { supplier: 'Ferguson', email: 'b@x.com', kind: 'decline', error: 'Gmail is rate limiting this mailbox (HTTP 429) — wait a few minutes and retry.' }
  const AWARDED = { status: 'awarded', message: 'Awarded Water Utilities for $10,500 — 1 PO to Core & Main. 1 supplier notified. 1 notification could not be sent: Ferguson (Gmail is rate limiting this mailbox (HTTP 429) — wait a few minutes and retry.).', total: 10500, material: 10000, freight: 500, leadDays: 10, suppliers: ['Core & Main'], poCount: 1, notified: 1, declined: 0, withdrawn: 0, notifyFailed: [FAILED], notifyMocked: false }

  it('lists the failed notices after an award and re-sends only those on click', async () => {
    const resends: unknown[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/quotes')) return json(QUOTES)
      if (path.includes('/line-comparison')) return json(LC)
      if (path.endsWith('/award') && init && init.method === 'POST') return json(AWARDED)
      if (path.endsWith('/award/notify') && init && init.method === 'POST') { resends.push(JSON.parse(String(init.body))); return json({ message: '1 supplier notified.', notified: 0, declined: 1, withdrawn: 0, notifyFailed: [], notifyMocked: false }) }
      return undefined
    }))
    await openProject('quotes')
    fireEvent.click(await screen.findByRole('button', { name: 'Compare' }))
    fireEvent.click(await screen.findByRole('button', { name: /Submit award/ }))
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Confirm award' }))
    await screen.findByText(/1 notification could not be sent/)
    expect(screen.getByText(/Ferguson \(b@x.com\): Gmail is rate limiting/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Re-send 1 failed notification' }))
    await screen.findByText('1 supplier notified.')
    expect(resends).toEqual([{ all: false }])
    expect(screen.queryByRole('button', { name: /Re-send/ })).toBeNull()
  })
})

describe('RFQ modal attachments', () => {
  const DOC = (id: string, name: string, fileSize: number) => ({
    id, name, type: 'PDF', date: 'Sep 1', status: 'Analyzed', statusTone: 'success', items: '0', pages: 1,
    processing: false, hasFile: true, fileMissing: false, fileSize, reviewed: true,
  })
  const OLD = DOC('d-1', 'Site plan.pdf', 5 * 1024 * 1024)
  const NEW = DOC('d-2', 'Specs uploaded later.pdf', 6 * 1024 * 1024)
  const BIG = DOC('d-3', 'Huge scan.pdf', 11 * 1024 * 1024)
  const DRAFT = {
    ...RFQ_BASE, status: 'Draft', statusTone: 'gray', recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com' }],
    attachments: [{ documentId: 'd-1', name: OLD.name }, { documentId: 'd-2', name: NEW.name }],
  }

  it('reads the documents fresh when it opens, lists newly uploaded ones and keeps the saved ids', async () => {
    let docCalls = 0
    const saves: { attachment_ids?: string[]; attachmentIds?: string[] }[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/documents')) { docCalls++; return json(docCalls === 1 ? [OLD] : [OLD, NEW, BIG]) }  // bundle is stale; modal fetch is fresh
      if (path.endsWith('/rfqs/generated')) return json([DRAFT])
      if (path.endsWith('/rfqs/rfq-1') && init && init.method === 'PUT') { saves.push(JSON.parse(String(init.body))); return json(DRAFT) }
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(DRAFT.subject))
    await screen.findByText(NEW.name)
    expect(screen.queryByText(/no longer exists/)).toBeNull()
    await screen.findByText(/Attachments \(2 · 11 MB\)/)
    expect(screen.getByText('5.0 MB')).toBeTruthy()
    // Edit the body so Save is enabled, then save: both original ids go out.
    fireEvent.change(screen.getByDisplayValue('Please quote.'), { target: { value: 'Please quote soon.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(saves).toHaveLength(1))
    const sent = saves[0].attachment_ids || saves[0].attachmentIds
    expect(sent).toEqual(['d-1', 'd-2'])
  })

  it('keeps the saved attachments untouched and says so when the refresh fails', async () => {
    let docCalls = 0
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/documents')) { docCalls++; return docCalls === 1 ? json([OLD]) : json({ detail: 'boom' }, 500) }
      if (path.endsWith('/rfqs/generated')) return json([DRAFT])
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(DRAFT.subject))
    await screen.findByText(/Couldn’t refresh the project’s documents/)
    expect(screen.queryByText(/no longer exists/)).toBeNull()
    await screen.findByText(/Attachments \(2/)
  })

  it('shows sizes, blocks Save/Send over 15 MB with the reason, and clears it when a file is unticked', async () => {
    let docCalls = 0
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/documents')) { docCalls++; return json([OLD, NEW, BIG]) }
      if (path.endsWith('/rfqs/generated')) return json([DRAFT])
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(DRAFT.subject))
    await screen.findByText(BIG.name)
    fireEvent.click(screen.getByText(BIG.name))
    await screen.findByText(/Attachments total 22 MB — over the 15 MB email limit/)
    const save = screen.getByRole('button', { name: 'Save draft' }) as HTMLButtonElement
    const send = screen.getByRole('button', { name: /Send to 1 supplier/ }) as HTMLButtonElement
    expect(save.disabled && send.disabled).toBe(true)
    expect(send.title).toMatch(/over the 15 MB email limit/)
    fireEvent.click(screen.getByText(BIG.name))
    await waitFor(() => expect(screen.queryByText(/over the 15 MB email limit/)).toBeNull())
    expect((screen.getByRole('button', { name: /Send to 1 supplier/ }) as HTMLButtonElement).disabled).toBe(false)
    await screen.findByText(/11 MB selected/)
  })
})
