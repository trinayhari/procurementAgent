// Thin client for the Proq FastAPI backend. Returns the raw data bundle
// that buildModel() consumes; the model decorates it with styles. If the API is
// unavailable, callers fall back to the literals baked into model.ts.
//
// All payload shapes are sourced from `api-types.ts`, which is generated from the
// backend's OpenAPI schema via `npm run gen:api`. Keep that in sync with the
// Python/Pydantic models rather than hand-editing types here.
import type { components } from './api-types'

type Schemas = components['schemas']

// Convenience aliases for the payloads this client touches.
export type Dashboard = Schemas['Dashboard']
export type Project = Schemas['Project']
export type ProjectDetail = Schemas['ProjectDetail']
export type Supplier = Schemas['Supplier']
export type SupplierDetail = Schemas['SupplierDetail']
export type Document = Schemas['Document']
export type PlanType = Schemas['PlanType']
export type LineItemGroup = Schemas['LineItemGroup']
export type Quote = Schemas['Quote']
export type Comparison = Schemas['Comparison']
export type Rfq = Schemas['Rfq']
export type RfqFolder = Schemas['RfqFolder']
export type Timeline = Schemas['Timeline']
export type Metric = Schemas['Metric']
export type Activity = Schemas['Activity']
export type OverviewCard = Schemas['OverviewCard']
export type Package = Schemas['Package']
export type SupplierComm = Schemas['SupplierComm']
export type Milestone = Schemas['Milestone']
export type GanttBar = Schemas['GanttBar']
// Supplier sourcing + generated RFQs.
export type FoundSupplier = Schemas['FoundSupplier']
export type SupplierTier = Schemas['SupplierTier']
export type SupplierSearchResult = Schemas['SupplierSearchResult']
export type PackageBom = Schemas['PackageBom']
export type CustomBomSummary = Schemas['CustomBomSummary']
export type PersistedRfq = Schemas['PersistedRfq']
export type RfqRecipient = Schemas['RfqRecipient']
export type RfqLineItem = Schemas['RfqLineItem']

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// ----------------------------------------------------------------- auth token
// The JWT minted by /api/auth/login is kept in localStorage and attached as a
// Bearer header to every request. Components subscribe to changes via onAuthChange.
const TOKEN_KEY = 'procureai_token'
const authListeners = new Set<() => void>()

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable (private mode) — token stays in-memory only this session */
  }
  authListeners.forEach((fn) => fn())
}

// Subscribe to login/logout; returns an unsubscribe fn.
export function onAuthChange(fn: () => void): () => void {
  authListeners.add(fn)
  return () => authListeners.delete(fn)
}

// Bearer header for the current token (empty when logged out).
export function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

// A 401 means the token is missing/expired — drop it so the app falls back to login.
function onUnauthorized(status: number): void {
  if (status === 401) setToken(null)
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: { ...authHeaders() } })
  if (!res.ok) {
    onUnauthorized(res.status)
    throw new Error(`${path} -> ${res.status}`)
  }
  return res.json() as Promise<T>
}

export function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  }).then(async (r) => {
    if (!r.ok) {
      onUnauthorized(r.status)
      // Surface the backend's human-readable reason (e.g. "RFQ was already
      // sent", BOM approval gate) instead of a bare status code.
      const data = await r.json().catch(() => null)
      const detail = data && typeof data.detail === 'string' ? data.detail : null
      throw new Error(detail || `${path} -> ${r.status}`)
    }
    return r.json() as Promise<T>
  })
}

// ------------------------------------------------------------------ auth API
export type AuthUser = Schemas['User']
type TokenResponse = Schemas['TokenResponse']

// Surface a friendly message for the auth screen rather than a bare status code.
async function authRequest(path: string, body: unknown): Promise<TokenResponse> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error((data && data.detail) || `Request failed (${res.status})`)
  }
  return data as TokenResponse
}

// Log in with email + password; persists the token and returns the user.
export async function login(email: string, password: string): Promise<AuthUser> {
  const data = await authRequest('/api/auth/login', { email, password })
  setToken(data.accessToken)
  return data.user
}

// Register a new account; logs in (persists token) on success.
export async function register(input: {
  email: string
  password: string
  name?: string
  company?: string
}): Promise<AuthUser> {
  const data = await authRequest('/api/auth/register', input)
  setToken(data.accessToken)
  return data.user
}

// Resolve the current token to a user (used to restore the session on load).
export function getMe(): Promise<AuthUser> {
  return get<AuthUser>('/api/auth/me')
}

// Update account settings; `ccEmail: null` stops copying you on outgoing mail.
// It is never a From address — everything is sent from the workspace mailbox.
export async function updateMe(input: { ccEmail: string | null }): Promise<AuthUser> {
  const res = await fetch(`${BASE}/api/auth/me`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    if (res.status === 422) throw new Error('Enter a valid email address')
    throw new Error(`Save failed (${res.status})`)
  }
  return res.json() as Promise<AuthUser>
}

// Verify the email configuration: sends a test message to your own account
// email via the same path an RFQ uses. mocked=true means no Gmail configured.
export type TestEmailResult = Schemas['TestEmailResult']
export function sendTestEmail(): Promise<TestEmailResult> {
  return post<TestEmailResult>('/api/auth/test-email')
}

// The workspace's effective outbound-email setup, derived from the backend's
// PROCUREAI_GMAIL_* environment variables. `configured: false` means nothing is
// actually delivered, and `senderAddressSet: false` means `fromAddress` is only
// a placeholder — surface both rather than implying mail is going out.
export type EmailConfig = Schemas['EmailConfig']
export function getEmailConfig(): Promise<EmailConfig> {
  return get<EmailConfig>('/api/auth/email-config')
}

export function logout(): void {
  setToken(null)
}

// ------------------------------------------------------- document extraction
// Plan types the backend extractor supports (drives the upload selector).
export function getPlanTypes(): Promise<PlanType[]> {
  return get<PlanType[]>('/api/documents/plan-types')
}

// Upload a plan set; the backend creates the doc in 'Processing' and runs
// GPT-4.1 vision extraction in the background. Returns the new Document.
export function uploadDocument(
  file: File,
  planType?: string,
  projectId?: string,
): Promise<Document> {
  const form = new FormData()
  form.append('file', file)
  if (planType) form.append('plan_type', planType)
  if (projectId) form.append('project_id', projectId)
  return fetch(`${BASE}/api/documents`, { method: 'POST', headers: { ...authHeaders() }, body: form }).then((r) => {
    if (!r.ok) throw new Error(`upload -> ${r.status}`)
    return r.json() as Promise<Document>
  })
}

// Page count + signed URLs for the document preview. Pages are rendered to
// images server-side (embedded webviews have no PDF plugin, so an <iframe> of
// the original renders blank there), and `pageUrl` is a template we fill per
// page. `pages: 0` means nothing renderable — the UI offers the original file.
export type DocumentPreview = Schemas['DocumentPreview']

export async function getDocumentPreview(docId: string): Promise<{
  pages: number
  pageUrl: (page: number) => string
  fileUrl: string
}> {
  const data = await get<DocumentPreview>(`/api/documents/${docId}/preview`)
  const template = data.pageUrl
  return {
    pages: data.pages,
    pageUrl: (page: number) =>
      template ? `${BASE}${template.replace('{page}', String(page))}` : '',
    fileUrl: `${BASE}${data.fileUrl}`,
  }
}

// BOM groups extracted from a single document.
export function getDocumentLineItems(docId: string): Promise<LineItemGroup[]> {
  return get<LineItemGroup[]>(`/api/documents/${docId}/line-items`)
}

// Human-in-the-loop: save a reviewer's edited BOM (full replacement of groups).
export function saveDocumentLineItems(
  docId: string,
  groups: LineItemGroup[],
): Promise<LineItemGroup[]> {
  return fetch(`${BASE}/api/documents/${docId}/line-items`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ groups }),
  }).then((r) => {
    if (!r.ok) throw new Error(`save line-items -> ${r.status}`)
    return r.json() as Promise<LineItemGroup[]>
  })
}

// Human-in-the-loop: mark a document's BOM as reviewed/approved.
export function confirmDocument(docId: string): Promise<Document> {
  return post<Document>(`/api/documents/${docId}/confirm`)
}

// Delete a document, its extracted BOM, and any uploaded source file.
// Human check-off for an extracted timeline milestone. Applies to every
// same-named event in the project; returns how many were updated.
export function setTimelineEventDone(eventId: number, done: boolean): Promise<{ updated: number }> {
  return post(`/api/timeline/events/${eventId}/done`, { done })
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/documents/${docId}`, { method: 'DELETE', headers: { ...authHeaders() } })
  if (!res.ok) throw new Error(`delete document -> ${res.status}`)
}

// ------------------------------------------------------------------ lenders
// A project's financing contacts — the people who'll receive timeline-driven
// progress emails (PRO-16). Plain per-project CRUD.
export type Lender = Schemas['Lender']
export type LenderCreate = Schemas['LenderCreate']

export function listLenders(projectId: string): Promise<Lender[]> {
  return get<Lender[]>(`/api/projects/${projectId}/lenders`)
}

export function createLender(projectId: string, payload: LenderCreate): Promise<Lender> {
  return post<Lender>(`/api/projects/${projectId}/lenders`, payload)
}

export async function deleteLender(projectId: string, lenderId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/projects/${projectId}/lenders/${lenderId}`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(`delete lender -> ${res.status}`)
}

// Delete a project and everything scoped to it (documents, quotes, RFQs, suppliers).
export async function deleteProject(projectId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/projects/${projectId}`, { method: 'DELETE', headers: { ...authHeaders() } })
  if (!res.ok) throw new Error(`delete project -> ${res.status}`)
}

// ------------------------------------------------------- supplier sourcing
// Kick off a background Places search for one project + buy-package. The
// frontend then polls getFoundSuppliers until status leaves 'searching'.
export function searchSuppliers(
  projectId: string,
  pkg: string,
  radiusMi: number,
): Promise<{ status: string; package: string }> {
  return post(`/api/projects/${projectId}/packages/${pkg}/search-suppliers`, {
    radius_mi: radiusMi,
  })
}

// Found suppliers for a package, bucketed into distance tiers.
export function getFoundSuppliers(
  projectId: string,
  pkg: string,
): Promise<SupplierSearchResult> {
  return get<SupplierSearchResult>(
    `/api/projects/${projectId}/suppliers/found?package=${encodeURIComponent(pkg)}`,
  )
}

// The BOM line items a buy-package will ask suppliers to quote — drives the
// "what we're asking for" panel on the supplier page.
export function getPackageBom(
  projectId: string,
  pkg: string,
): Promise<PackageBom> {
  return get<PackageBom>(
    `/api/projects/${projectId}/packages/${encodeURIComponent(pkg)}/bom`,
  )
}

// -------------------------------------------------------- supplier directory
// The customer's own supplier network (the top-level Suppliers page). Add a
// supplier manually there, or from a project's search results. Idempotent by
// name server-side, so saving the same supplier twice is a no-op.
export type SupplierCreate = Schemas['SupplierCreate']
export type SupplierUpdate = Schemas['SupplierUpdate']

export function createSupplier(payload: SupplierCreate): Promise<Supplier> {
  return post<Supplier>('/api/suppliers', payload)
}

// Edit a supplier already in the network. Only the fields present in `payload`
// are changed; the supplier id is stable even when the name changes.
export async function updateSupplier(
  supplierId: string,
  payload: SupplierUpdate,
): Promise<Supplier> {
  const res = await fetch(`${BASE}/api/suppliers/${supplierId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    if (res.status === 409) throw new Error('Another supplier already has that name')
    throw new Error(`update supplier -> ${res.status}`)
  }
  return res.json() as Promise<Supplier>
}

// One supplier's full detail, including its own communication history. Fetched
// on demand when the supplier drawer opens (the timeline is per-supplier).
export function getSupplierDetail(supplierId: string): Promise<SupplierDetail> {
  return get<SupplierDetail>(`/api/suppliers/${supplierId}`)
}

// Remove a supplier from the customer's network.
export function deleteSupplier(supplierId: string): Promise<void> {
  return fetch(`${BASE}/api/suppliers/${supplierId}`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  }).then((r) => {
    if (!r.ok) throw new Error(`delete supplier -> ${r.status}`)
  })
}

// ------------------------------------------------------------- generated RFQs
// Generate a draft RFQ for a package from the chosen found-supplier ids.
export function generateRfq(
  projectId: string,
  pkg: string,
  supplierIds: string[],
): Promise<PersistedRfq> {
  return post<PersistedRfq>(`/api/projects/${projectId}/packages/${pkg}/rfqs/generate`, {
    supplier_ids: supplierIds,
  })
}

export function listGeneratedRfqs(projectId: string): Promise<PersistedRfq[]> {
  return get<PersistedRfq[]>(`/api/projects/${projectId}/rfqs/generated`)
}

// ----------------------------------------------------- custom (ad-hoc) BOMs
// A custom BOM is a hand-built bill of materials created in the Documents panel.
// It shows up as a selectable "package" in the supplier search (its document id
// is the package key), so the same find-suppliers → select → generate flow works
// with no separate ad-hoc code path.

// Create a new empty custom BOM document; returns the created Document.
export function createManualBom(projectId: string, name: string): Promise<Document> {
  return post<Document>('/api/documents/manual', { name, projectId })
}

// The project's custom BOMs — the selectable custom packages in the search.
export function listProjectBoms(projectId: string): Promise<CustomBomSummary[]> {
  return get<CustomBomSummary[]>(`/api/projects/${projectId}/boms`)
}

export function saveRfq(
  projectId: string,
  rfqId: string,
  patch: { subject: string; body: string; recipients: RfqRecipient[] },
): Promise<PersistedRfq> {
  return fetch(`${BASE}/api/projects/${projectId}/rfqs/${rfqId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  }).then((r) => {
    if (!r.ok) throw new Error(`save rfq -> ${r.status}`)
    return r.json() as Promise<PersistedRfq>
  })
}

// The full email conversation for an RFQ, read live from Gmail when configured.
// Read-only: surfaces the original thread (our outbound + any threaded supplier
// replies) without changing the RFQ's status.
export type RfqConversation = Schemas['RfqConversation']
export function getRfqConversation(projectId: string, rfqId: string): Promise<RfqConversation> {
  return get<RfqConversation>(`/api/projects/${projectId}/rfqs/${rfqId}/conversation`)
}

// Delete an RFQ (e.g. an unwanted draft).
export function deleteRfq(projectId: string, rfqId: string): Promise<void> {
  return fetch(`${BASE}/api/projects/${projectId}/rfqs/${rfqId}`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  }).then((r) => {
    if (!r.ok) throw new Error(`delete rfq -> ${r.status}`)
  })
}

// User-approved send: delivers the RFQ to every recipient via Gmail (or the
// logging mock when Gmail is unconfigured). Attaches a line-item PDF and flips
// the RFQ to 'Awaiting' (awaiting supplier quotes).
export function sendRfq(projectId: string, rfqId: string): Promise<PersistedRfq> {
  return post<PersistedRfq>(`/api/projects/${projectId}/rfqs/${rfqId}/send`)
}

// ------------------------------------------------------------- quote ingest
export type QuoteIngestResult = Schemas['QuoteIngestResult']

// Kick off reading supplier quote replies (Gmail) for a project. Background
// task; poll getIngestStatus until it leaves 'ingesting', then reload the model.
export function ingestQuotes(projectId: string): Promise<QuoteIngestResult> {
  return post<QuoteIngestResult>(`/api/projects/${projectId}/quotes/ingest`)
}

export function getIngestStatus(projectId: string): Promise<QuoteIngestResult> {
  return get<QuoteIngestResult>(`/api/projects/${projectId}/quotes/ingest-status`)
}

// Select a quote and issue a purchase order.
export function selectQuote(
  quoteId: string,
): Promise<{ quote_id: string; status: string; message: string }> {
  return post(`/api/quotes/${quoteId}/select`)
}

// ----------------------------------------------------- line-by-line comparison
export type LineComparison = Schemas['LineComparison']
export type AwardOption = Schemas['AwardOption']
export type AwardResult = Schemas['AwardResult']

// Line-by-line quote grid for a package + freight-aware mix-and-match strategies.
// `pkg` may be a package key ("water") or display label ("Water Utilities").
export function getLineComparison(
  projectId: string,
  pkg: string,
): Promise<LineComparison> {
  return get<LineComparison>(
    `/api/projects/${projectId}/packages/${encodeURIComponent(pkg)}/line-comparison`,
  )
}

// Submit a (possibly split) award — selections map each line name to a supplier id.
export function awardPackage(
  projectId: string,
  pkg: string,
  selections: Record<string, string>,
  strategy?: string,
): Promise<AwardResult> {
  return post<AwardResult>(
    `/api/projects/${projectId}/packages/${encodeURIComponent(pkg)}/award`,
    { selections, strategy },
  )
}

// The reshaped bundle that buildModel() consumes. Mirrors the keys returned by
// loadModelData() below.
export type ModelData = {
  metrics: Metric[]
  activity: Activity[]
  projectActivity: Activity[]
  projects: Project[]
  overviewCards: OverviewCard[]
  packages: Package[]
  suppliers: Supplier[]
  docs: Document[]
  lineItems: LineItemGroup[]
  quotes: Quote[]
  comparison: {
    suppliers: Comparison['suppliers']
    rows: Comparison['rows']
    recommendation: string
    reasons: string[]
    savings: string
    savingsNote: string
  }
  rfqs: Rfq[]
  rfqFolders: RfqFolder[]
  milestones: Milestone[]
  gantt: GanttBar[]
  ganttCols: string[]
}

// Fetches everything the current workspace renders, in parallel, and reshapes it
// into the keys buildModel() expects.
//
// Resilient by design: the global lists (dashboard, projects, suppliers) load
// first, then the per-project bundle is hydrated for whichever real project
// applies — the requested id if it still exists, else the first project, else
// none (a brand-new/empty account). Each fetch falls back to an empty value on
// error so a single missing sub-resource (or zero projects) can never blank the
// whole UI.
export async function loadModelData(projectId?: string): Promise<ModelData> {
  const pkg = encodeURIComponent('Water Utilities')
  const safe = <T>(p: Promise<T>, fb: T): Promise<T> => p.catch(() => fb)

  const [dashboard, projects, suppliers] = await Promise.all([
    safe(get<Dashboard>('/api/dashboard'), { metrics: [], activity: [] } as Dashboard),
    safe(get<Project[]>('/api/projects'), [] as Project[]),
    safe(get<Supplier[]>('/api/suppliers'), [] as Supplier[]),
  ])

  // Pick a real project/supplier to hydrate; null when the account is empty.
  const pid =
    (projectId && projects.some((p) => p.id === projectId) ? projectId : null) ||
    (projects[0] ? projects[0].id : null)

  // Per-project fetch that short-circuits to its fallback when there's no project.
  const proj = <T>(path: string, fb: T): Promise<T> => (pid ? safe(get<T>(path), fb) : Promise.resolve(fb))
  const emptyComparison = { suppliers: [], rows: [], recommendation: '', reasons: [], savings: '', savingsNote: '' } as unknown as Comparison
  const emptyTimeline = { milestones: [], gantt: [], ganttCols: [] } as unknown as Timeline

  const [detail, docs, lineItems, quotes, comparison, rfqs, rfqFolders, timeline] =
    await Promise.all([
      proj(`/api/projects/${pid}`, { overviewCards: [], packages: [], activity: [] } as unknown as ProjectDetail),
      proj(`/api/projects/${pid}/documents`, [] as Document[]),
      proj(`/api/projects/${pid}/line-items`, [] as LineItemGroup[]),
      proj(`/api/projects/${pid}/quotes`, [] as Quote[]),
      proj(`/api/projects/${pid}/packages/${pkg}/comparison`, emptyComparison),
      proj(`/api/projects/${pid}/rfqs`, [] as Rfq[]),
      proj(`/api/projects/${pid}/rfq-folders`, [] as RfqFolder[]),
      proj(`/api/projects/${pid}/timeline`, emptyTimeline),
    ])

  return {
    metrics: dashboard.metrics,
    activity: dashboard.activity,
    projectActivity: detail.activity || [],
    projects,
    overviewCards: detail.overviewCards,
    packages: detail.packages,
    suppliers,
    docs,
    lineItems,
    quotes,
    comparison: {
      suppliers: comparison.suppliers,
      rows: comparison.rows,
      recommendation: comparison.recommendation,
      reasons: comparison.reasons,
      savings: comparison.savings,
      savingsNote: comparison.savingsNote,
    },
    rfqs,
    rfqFolders,
    milestones: timeline.milestones,
    gantt: timeline.gantt,
    ganttCols: timeline.ganttCols,
  }
}
