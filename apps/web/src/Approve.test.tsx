// The public approval page (#/approve/<token>): shows the award card, one
// click issues the POs and lists their numbers, and a spent / expired /
// unknown link says so. Also checks App renders it ahead of the login gate.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import Approve from './Approve'
import App from './App'
import { makeFetch, json, resetDom } from './testUtils'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
beforeEach(() => { resetDom() })

const TOKEN = 'tok-abc'
const PREVIEW = {
  status: 'pending', projectId: 'p-1', projectName: 'Riverside WTP', package: 'water', packageLabel: 'Water Utilities',
  suppliers: [
    { supplierId: 's1', supplierName: 'Core & Main', subtotal: 18000, freight: 420, total: 18420, leadDays: 14 },
    { supplierId: 's2', supplierName: 'Ferguson', subtotal: 9000, freight: 300, total: 9300, leadDays: 16 },
  ],
  total: 27720, material: 27000, freight: 720, leadDays: 16, savings: 1620,
  quotesReceived: 5, recipientsTotal: 7, expiresAt: '2026-10-05T00:00:00', decidedAt: null, decidedByEmail: null,
  alreadyAwarded: false,
}
const RESULT = {
  status: 'awarded', message: 'Awarded Water Utilities for $27,720: 2 POs to Core & Main, Ferguson. 2 suppliers notified.',
  total: 27720, material: 27000, freight: 720, leadDays: 16, suppliers: ['Core & Main', 'Ferguson'], poCount: 2,
  poNumbers: [
    { supplierId: 's1', supplierName: 'Core & Main', po: 'PO-12-0042' },
    { supplierId: 's2', supplierName: 'Ferguson', po: 'PO-12-0043' },
  ],
  notified: 2, declined: 0, withdrawn: 0, notifyFailed: [], notifyMocked: true,
  projectId: 'p-1', packageLabel: 'Water Utilities', decidedByEmail: null,
}

describe('Approve page', () => {
  it('shows the card, approves on one click and lists the PO numbers', async () => {
    const posts: string[] = []
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === `/api/approvals/${TOKEN}` && (!init || !init.method)) return json(PREVIEW)
      if (path === `/api/approvals/${TOKEN}` && init && init.method === 'POST') { posts.push(String(init.body)); return json(RESULT) }
      return undefined
    }))
    render(<Approve token={TOKEN} onDismiss={() => {}} />)
    expect(await screen.findByText('Approve Water Utilities award')).toBeTruthy()
    expect(screen.getByText(/5 of 7 suppliers/)).toBeTruthy()
    expect(screen.getByText(/\$1,620 under best single bid/)).toBeTruthy()
    expect(screen.getByText('Core & Main')).toBeTruthy()
    expect(screen.getByText('$18,420')).toBeTruthy()
    expect(screen.getByText('$27,720')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Approve award' }))
    expect(await screen.findByText('Award approved')).toBeTruthy()
    expect(posts).toHaveLength(1)
    expect(screen.getByText('PO-12-0042')).toBeTruthy()
    expect(screen.getByText('PO-12-0043')).toBeTruthy()
    expect(screen.getByText('Ferguson')).toBeTruthy()
    // The button is gone: nothing to double-submit.
    expect(screen.queryByRole('button', { name: 'Approve award' })).toBeNull()
  })

  it('explains a used link, an expired link and an unknown one', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === `/api/approvals/used`) return json({ ...PREVIEW, status: 'used', decidedByEmail: 'pm@acmebuild.com', decidedAt: '2026-09-20T10:00:00' })
      if (path === `/api/approvals/old`) return json({ ...PREVIEW, status: 'expired' })
      if (path === `/api/approvals/nope`) return json({ detail: 'This approval link is not valid' }, 404)
      return undefined
    }))
    render(<Approve token="used" onDismiss={() => {}} />)
    expect(await screen.findByText(/already approved by pm@acmebuild.com/)).toBeTruthy()
    cleanup()
    render(<Approve token="old" onDismiss={() => {}} />)
    expect(await screen.findByText(/link has expired/)).toBeTruthy()
    cleanup()
    render(<Approve token="nope" onDismiss={() => {}} />)
    expect(await screen.findByText(/isn't valid/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Approve award' })).toBeNull()
  })

  it('keeps the card and shows the reason when the award is refused', async () => {
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === `/api/approvals/${TOKEN}` && (!init || !init.method)) return json(PREVIEW)
      if (init && init.method === 'POST') return json({ detail: 'Water Utilities was already awarded to Ferguson.' }, 409)
      return undefined
    }))
    render(<Approve token={TOKEN} onDismiss={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve award' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText(/already awarded to Ferguson/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Approve award' })).toBeTruthy()
  })

  it('turns a 410 on click into the spent state', async () => {
    vi.stubGlobal('fetch', makeFetch((path, init) => {
      if (path === `/api/approvals/${TOKEN}` && (!init || !init.method)) return json(PREVIEW)
      if (init && init.method === 'POST') return json({ detail: 'This award was already approved' }, 410)
      return undefined
    }))
    render(<Approve token={TOKEN} onDismiss={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve award' }))
    expect(await screen.findByText(/already approved/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Approve award' })).toBeNull()
  })
})

describe('App routing', () => {
  it('renders the approval page for #/approve/<token> before the login gate', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === `/api/approvals/${TOKEN}`) return json(PREVIEW)
      return undefined
    }))
    window.location.hash = `#/approve/${TOKEN}`
    render(<App />)
    expect(await screen.findByText('Approve Water Utilities award')).toBeTruthy()
    expect(screen.queryByPlaceholderText('you@company.com')).toBeNull()
  })

  it('dismissing an unavailable link lands on the app (login when signed out)', async () => {
    vi.stubGlobal('fetch', makeFetch((path) => {
      if (path === '/api/approvals/nope') return json({ detail: 'This approval link is not valid' }, 404)
      return undefined
    }))
    window.location.hash = '#/approve/nope'
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Open the dashboard' }))
    await waitFor(() => expect(window.location.hash).toBe('#/dashboard'))
    expect(await screen.findByPlaceholderText('you@company.com')).toBeTruthy()
  })
})
