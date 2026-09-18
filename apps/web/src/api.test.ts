// Error plumbing in the API client: a failed request must carry the backend's
// own reason (an HTTPException `detail` string, or the first message of a 422
// validation list) so screens can show "File exceeds 100MB limit" instead of
// "upload -> 413".
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { errorDetail, hasDetail, uploadDocument, saveRfq, analyzeDocument } from './api'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let nextResponse: Response
const fetchMock = vi.fn(async () => nextResponse)

beforeEach(() => {
  localStorage.clear()
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('errorDetail', () => {
  it('reads an HTTPException string detail', () => {
    expect(errorDetail({ detail: 'File exceeds 100MB limit' })).toBe('File exceeds 100MB limit')
  })

  it('reads the first message of a 422 validation list, without the pydantic prefix', () => {
    const body = { detail: [{ loc: ['body', 'recipients'], msg: "Value error, 'x' is not a valid email address", type: 'value_error' }] }
    expect(errorDetail(body)).toBe("'x' is not a valid email address")
  })

  it('is null for anything else', () => {
    expect(errorDetail(null)).toBeNull()
    expect(errorDetail({ detail: [] })).toBeNull()
    expect(errorDetail({ detail: '' })).toBeNull()
    expect(errorDetail('nope')).toBeNull()
  })
})

describe('hasDetail', () => {
  it('distinguishes a backend reason from a bare "<path> -> <status>" code', () => {
    expect(hasDetail(new Error('The file is empty'))).toBe(true)
    expect(hasDetail(new Error('upload -> 500'))).toBe(false)
    expect(hasDetail(new Error(''))).toBe(false)
    expect(hasDetail('string')).toBe(false)
  })
})

describe('uploadDocument', () => {
  it('rejects with the backend reason when the upload is refused', async () => {
    nextResponse = json({ detail: 'File exceeds 100MB limit' }, 413)
    const file = new File([new Uint8Array([1, 2, 3])], 'plan.pdf', { type: 'application/pdf' })
    await expect(uploadDocument(file, 'site_plan', 'p-1')).rejects.toThrow('File exceeds 100MB limit')
  })

  it('falls back to a status code when the backend gives no reason', async () => {
    nextResponse = new Response('boom', { status: 502 })
    const file = new File([new Uint8Array([1])], 'plan.pdf')
    await expect(uploadDocument(file)).rejects.toThrow('upload -> 502')
  })
})

describe('saveRfq', () => {
  it('surfaces a 422 validation message as a sentence', async () => {
    nextResponse = json({ detail: [{ loc: ['body', 'recipients'], msg: "Value error, 'nope' is not a valid email address" }] }, 422)
    await expect(
      saveRfq('p-1', 'rfq-1', { subject: 's', body: 'b', recipients: [{ name: 'X', email: 'nope' }] }),
    ).rejects.toThrow("'nope' is not a valid email address")
  })
})

describe('analyzeDocument', () => {
  it('POSTs to the analyze endpoint and surfaces a 410 file-gone reason', async () => {
    nextResponse = json({ detail: 'The uploaded file is no longer available on this server — re-upload the document to preview or re-analyze it' }, 410)
    await expect(analyzeDocument('doc-1')).rejects.toThrow(/no longer available/)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/api\/documents\/doc-1\/analyze$/)
    expect(init.method).toBe('POST')
  })
})
