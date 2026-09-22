// Email-workflow UI truthfulness: Settings names the missing AgentMail
// variable and the last AgentMail / AI error, the connection check is explicit
// (never on load), an RFQ conversation says when no supplier reply has arrived
// instead of passing off the stored copy as live, an undelivered RFQ is not "Sent", team
// invites surface a failed send with the link, and the Quotes table flags a
// reply that had no amount. Drives the real <App /> against a mocked fetch.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { makeFetch, openProject, resetDom, json, PROJECT, USER } from './testUtils'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
beforeEach(() => { resetDom() })

const AM_ERR = 'AgentMail rejected the API key (HTTP 401): check PROCUREAI_AGENTMAIL_API_KEY (docs/email-setup.md).'
const AM_429 = 'AgentMail is rate limiting this organization (HTTP 429): wait a minute and retry.'
const CFG_BASE = {
  configured: true, mocked: false, inboxAddress: 'acme@proq.tryproq.dev',
  fromHeader: 'Pat Mason: Acme Build Co. <acme@proq.tryproq.dev>', ccEmail: null, missing: [],
  agentmail: { lastError: null, lastErrorAt: null, lastOkAt: null },
  llm: { configured: true, model: 'gpt-4.1', baseUrl: null, lastError: null, lastErrorAt: null, lastErrorWhere: null, lastOkAt: null },
}

async function openSettings() {
  await openProject()
  fireEvent.click(screen.getAllByRole('button', { name: /Settings/ })[0])
  await screen.findByText('Email delivery')
}

describe('Settings → email delivery', () => {
  it('names the missing PROCUREAI_AGENTMAIL_API_KEY when not configured', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === '/api/auth/email-config') return json({ ...CFG_BASE, configured: false, mocked: true, inboxAddress: null, missing: ['PROCUREAI_AGENTMAIL_API_KEY'], llm: { ...CFG_BASE.llm, configured: false } })
      return undefined
    }))
    await openSettings()
    await screen.findByText('Not configured')
    expect(screen.getByText(/PROCUREAI_AGENTMAIL_API_KEY/)).toBeTruthy()
    expect(screen.getByText(/No AI key set/)).toBeTruthy()
  })

  it('shows the inbox once created, the last AgentMail failure and the AI parser outage, and checks connections only on click', async () => {
    const probes: string[] = []
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === '/api/auth/email-config') return json({
        ...CFG_BASE,
        agentmail: { lastError: AM_ERR, lastErrorAt: '2026-09-17T10:00:00Z', lastOkAt: null },
        llm: { ...CFG_BASE.llm, lastError: 'LLM rejected the API key (401) — an OpenAI sk-proj key is paired with the OpenRouter base URL; use an sk-or-… key or clear PROCUREAI_OPENAI_BASE_URL.', lastErrorWhere: 'quote parser' },
      })
      if (path === '/api/health/providers') {
        probes.push(path)
        return json({ ok: false, email: { ok: false, error: AM_ERR, inboxAddress: null }, llm: { ok: true, error: null, model: 'gpt-4.1' } })
      }
      return undefined
    }))
    await openSettings()
    await screen.findByText('acme@proq.tryproq.dev')
    await screen.findByText(/AgentMail is configured but the last call failed: AgentMail rejected the API key/)
    expect(screen.getByText(/AI parsing unavailable — LLM rejected the API key \(401\)/)).toBeTruthy()
    // Nothing probed on load.
    expect(probes).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Check connections' }))
    await screen.findByText(/^AgentMail: AgentMail rejected the API key/)
    await screen.findByText(/AI model: gpt-4.1 answered/)
    expect(probes).toHaveLength(1)
  })

  it('says the inbox is not created yet when configured but unused', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === '/api/auth/email-config') return json({ ...CFG_BASE, inboxAddress: null })
      return undefined
    }))
    await openSettings()
    await screen.findByText('Not created yet')
  })
})

const RFQ_BASE = {
  id: 'rfq-1', projectId: PROJECT.id, package: 'water', pkg: 'Water Utilities', sup: '', folder: '', preview: '', time: '',
  logo: 'WU', logoBg: '#334155', kind: 'materials', attachments: [], lineItems: [{ n: '12" DI Pipe', q: '100 LF' }],
  subject: 'RFQ: Water Utilities — Riverside Yard', body: 'Please quote.',
}

describe('RFQ conversation', () => {
  it('shows a stored supplier reply as live, with no local-preview notice', async () => {
    const SENT = { ...RFQ_BASE, status: 'Quoted', statusTone: 'success', recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com', sendStatus: 'sent', messageId: '<m1@agentmail.to>', sentMessageId: '<m1@agentmail.to>', threadId: 'thr-1', repliedAt: '2026-09-17T10:00:00Z' }] }
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/rfqs/generated')) return json([SENT])
      if (path.endsWith('/conversation')) return json({
        rfqId: 'rfq-1', status: 'Quoted', statusTone: 'success', live: true, configured: true,
        thread: [
          { dir: 'out', who: 'You · Proq', initials: 'YOU', time: 'Sep 16, 3:00 PM', subject: SENT.subject, body: SENT.body, attach: null, logoBg: null },
          { dir: 'in', who: 'Core & Main', initials: 'CM', time: 'Sep 17, 10:00 AM', subject: null, body: 'Grand total $10,500', attach: 'quote.pdf', logoBg: '#334155' },
        ],
      })
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(SENT.subject))
    await screen.findByText('Grand total $10,500')
    expect(screen.queryByText(/local preview/)).toBeNull()
    expect(screen.queryByText(/No supplier reply has reached/)).toBeNull()
  })

  it('labels an undelivered RFQ "Not delivered" in the stored thread', async () => {
    const FAILED = { ...RFQ_BASE, status: 'Send failed', statusTone: 'danger', recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com', sendStatus: 'failed', sendError: AM_ERR }] }
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/rfqs/generated')) return json([FAILED])
      if (path.endsWith('/conversation')) return json({
        rfqId: 'rfq-1', status: 'Send failed', statusTone: 'danger', live: false, configured: true,
        thread: [{ dir: 'out', who: 'You · Proq', initials: 'YOU', time: 'Not delivered', subject: FAILED.subject, body: FAILED.body, attach: null, logoBg: null }],
      })
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(FAILED.subject))
    await screen.findByText('Not delivered')
    expect(screen.getByText(/HTTP 401/)).toBeTruthy()
    await screen.findByText(/No supplier reply has reached the agent inbox/)
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
    const INVITE = { id: 'inv-1', email: 'newbie@example.com', status: 'pending', invitedByUserId: USER.id, createdAt: null, expiresAt: null, acceptedAt: null, emailed: false, emailedAt: null, emailError: AM_429, acceptUrl: 'http://localhost:5250/#/invite/tok-123' }
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === '/api/team') return json({ members: [USER], invites: [INVITE] })
      if (path === '/api/team/invites' && init && init.method === 'POST') return json(INVITE, 201)
      return undefined
    }))
    await openProject()
    fireEvent.click(screen.getAllByRole('button', { name: /Settings/ })[0])
    await screen.findByText('Team')
    await screen.findByText(/Invitation pending — email failed: AgentMail is rate limiting/)
    expect(screen.getByRole('button', { name: 'Copy invite link' })).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText(/teammate@/i), { target: { value: 'newbie@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: /Invite/ }))
    await screen.findByText(/but the email could not be sent: AgentMail is rate limiting/)
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
  const FAILED = { supplier: 'Ferguson', email: 'b@x.com', kind: 'decline', error: AM_429 }
  const AWARDED = { status: 'awarded', message: `Awarded Water Utilities for $10,500 — 1 PO to Core & Main. 1 supplier notified. 1 notification could not be sent: Ferguson (${AM_429}).`, total: 10500, material: 10000, freight: 500, leadDays: 10, suppliers: ['Core & Main'], poCount: 1, notified: 1, declined: 0, withdrawn: 0, notifyFailed: [FAILED], notifyMocked: false }

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
    expect(screen.getByText(/Ferguson \(b@x.com\): AgentMail is rate limiting/)).toBeTruthy()
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
  const OLD = DOC('d-1', 'Site plan.pdf', 1 * 1024 * 1024)
  const NEW = DOC('d-2', 'Specs uploaded later.pdf', 2 * 1024 * 1024)
  const BIG = DOC('d-3', 'Huge scan.pdf', 3 * 1024 * 1024)
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
    await screen.findByText(/Attachments \(2 · 3.0 MB\)/)
    expect(screen.getByText('1.0 MB')).toBeTruthy()
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

  it('shows sizes, blocks Save/Send over 4 MB with the reason, and clears it when a file is unticked', async () => {
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
    await screen.findByText(/Attachments total 6.0 MB — over the 4.0 MB email limit/)
    const save = screen.getByRole('button', { name: 'Save draft' }) as HTMLButtonElement
    const send = screen.getByRole('button', { name: /Send to 1 supplier/ }) as HTMLButtonElement
    expect(save.disabled && send.disabled).toBe(true)
    expect(send.title).toMatch(/over the 4.0 MB email limit/)
    fireEvent.click(screen.getByText(BIG.name))
    await waitFor(() => expect(screen.queryByText(/over the 4.0 MB email limit/)).toBeNull())
    expect((screen.getByRole('button', { name: /Send to 1 supplier/ }) as HTMLButtonElement).disabled).toBe(false)
    await screen.findByText(/3.0 MB selected/)
  })
})

describe('persisted award notification failures', () => {
  const LC = {
    pkg: 'Water Utilities', package: 'water', budget: null,
    suppliers: [{ id: 's1', name: 'Core & Main', logo: 'CM', logoBg: '#111', leadDays: 10, distanceMiles: 12, freight: 500, total: 10500 }],
    lines: [{ name: '12" DI Pipe', qty: '100 LF', pending: false, cells: [{ supplierId: 's1', unitPrice: 100, extended: 10000, leadDays: 10, available: true, best: true }] }],
    options: [{ key: 'mix', label: 'Lowest cost (mix & match)', total: 10500, material: 10000, freight: 500, leadDays: 10, suppliersUsed: 1, deliveries: 1, savings: 0, note: '', selections: { '12" DI Pipe': 's1' } }],
    recommendedOption: 'mix',
    lastAward: { id: 'pd-1', total: 10500, poCount: 1, suppliers: ['Core & Main'], createdAt: '2026-09-17T10:00:00', decidedBy: 'Pat Mason' },
  }
  const QUOTES = [{ id: 'q1', sup: 'Core & Main', pkg: 'Water Utilities', package: 'water', amount: '$10,000', freight: '$500', total: '$10,500', lead: '10 days', date: 'Sep 1', logo: 'CM', logoBg: '#111', best: true, status: 'received' }]
  const FAILED = { supplier: 'Core & Main', email: 'a@x.com', kind: 'award', error: AM_ERR }
  const DECISION = {
    id: 'pd-1', projectId: PROJECT.id, package: 'water', packageLabel: 'Water Utilities', strategy: 'mix', selections: { '12" DI Pipe': 's1' },
    supplierIds: ['s1'], suppliers: ['Core & Main'], total: 10500, material: 10000, freight: 500, leadDays: 10, poCount: 1,
    decidedBy: 'u-pm', decidedByEmail: USER.email, createdAt: '2026-09-17T10:00:00', status: 'active', supersededBy: null,
    notifications: { notified: [], declined: [], withdrawn: [], failed: [FAILED], mock: false, at: '2026-09-17T10:00:01' },
  }

  it('shows the failures and the re-send button on load, and clears them after a successful re-send', async () => {
    const resends: unknown[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path.endsWith('/quotes')) return json(QUOTES)
      if (path.includes('/line-comparison')) return json(LC)
      if (path.endsWith('/purchase-decisions')) return json([DECISION])
      if (path.endsWith('/award/notify') && init && init.method === 'POST') { resends.push(JSON.parse(String(init.body))); return json({ message: '1 supplier notified.', notified: 1, declined: 0, withdrawn: 0, notifyFailed: [], notifyMocked: false }) }
      return undefined
    }))
    await openProject('quotes')
    fireEvent.click(await screen.findByRole('button', { name: 'Compare' }))
    await screen.findByText(/1 supplier notification from the award on 2026-09-17 could not be sent/)
    expect(screen.getByText(/Core & Main \(a@x.com\): AgentMail rejected the API key/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Re-send 1 failed notification' }))
    await screen.findByText('1 supplier notified.')
    expect(resends).toEqual([{ all: false }])
    expect(screen.queryByRole('button', { name: /Re-send/ })).toBeNull()
  })
})

describe('mock-mode labels and package quote counts', () => {
  it('labels a mock send as logged, not delivered', async () => {
    const SENT = { ...RFQ_BASE, status: 'Awaiting', statusTone: 'warn', recipients: [{ supplierId: 's1', name: 'Core & Main', email: 'a@x.com', sendStatus: 'sent', sentMessageId: 'mock-1', threadId: 'mock-1', mock: true }] }
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path.endsWith('/rfqs/generated')) return json([SENT])
      if (path.endsWith('/conversation')) return json({ rfqId: 'rfq-1', status: 'Awaiting', statusTone: 'warn', live: false, configured: false, thread: [{ dir: 'out', who: 'You · Proq', initials: 'YOU', time: 'Logged only (mock, not delivered)', subject: SENT.subject, body: SENT.body, attach: null, logoBg: null }] })
      return undefined
    }))
    await openProject('rfqs')
    fireEvent.click(await screen.findByText(SENT.subject))
    await screen.findByText('Logged (mock)')
    await screen.findByText('Logged only (mock, not delivered)')
    await screen.findByText(/Showing a local preview: set the AgentMail key/)
  })

  it('does not count a needs-review reply in the package header', async () => {
    const QUOTES = [
      { id: 'q1', sup: 'Core & Main', pkg: 'Water Utilities', package: 'water', amount: '$10,000', freight: '$500', total: '$10,500', lead: '10 days', date: 'Sep 1', logo: 'CM', logoBg: '#111', best: true, status: 'received' },
      { id: 'q2', sup: 'Ferguson', pkg: 'Water Utilities', package: 'water', amount: '$11,000', freight: '$500', total: '$11,500', lead: '10 days', date: 'Sep 1', logo: 'FW', logoBg: '#222', best: false, status: 'received' },
      { id: 'q3', sup: 'Ghost Co', pkg: 'Water Utilities', package: 'water', amount: '—', freight: '—', total: '—', lead: '—', date: 'Sep 2', logo: 'GC', logoBg: '#333', best: false, status: 'needs_review' },
    ]
    vi.stubGlobal('fetch', makeFetch((path) => (path.endsWith('/quotes') ? json(QUOTES) : undefined)))
    await openProject('quotes')
    await screen.findByText('2 quotes · 1 to review')
  })
})
