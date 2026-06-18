// Thin client for the ProcureAI FastAPI backend. Returns the raw data bundle
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

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${path} -> ${res.status}`)
  return res.json() as Promise<T>
}

export function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => {
    if (!r.ok) throw new Error(`${path} -> ${r.status}`)
    return r.json() as Promise<T>
  })
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
  return fetch(`${BASE}/api/documents`, { method: 'POST', body: form }).then((r) => {
    if (!r.ok) throw new Error(`upload -> ${r.status}`)
    return r.json() as Promise<Document>
  })
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
    headers: { 'Content-Type': 'application/json' },
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

// The reshaped bundle that buildModel() consumes. Mirrors the keys returned by
// loadModelData() below.
export type ModelData = {
  metrics: Metric[]
  activity: Activity[]
  projects: Project[]
  overviewCards: OverviewCard[]
  packages: Package[]
  suppliers: Supplier[]
  supplierComms: SupplierComm[]
  docs: Document[]
  lineItems: LineItemGroup[]
  quotes: Quote[]
  comparison: { suppliers: Comparison['suppliers']; rows: Comparison['rows'] }
  rfqs: Rfq[]
  rfqFolders: RfqFolder[]
  milestones: Milestone[]
  gantt: GanttBar[]
  ganttCols: string[]
}

// Fetches everything the current single-project prototype renders, in parallel,
// and reshapes it into the keys buildModel() expects.
export async function loadModelData(projectId = 'riverside'): Promise<ModelData> {
  const pkg = encodeURIComponent('Water Utilities')
  const [dashboard, projects, detail, suppliers, supplierDetail, docs, lineItems, quotes, comparison, rfqs, rfqFolders, timeline] =
    await Promise.all([
      get<Dashboard>('/api/dashboard'),
      get<Project[]>('/api/projects'),
      get<ProjectDetail>(`/api/projects/${projectId}`),
      get<Supplier[]>('/api/suppliers'),
      get<SupplierDetail>('/api/suppliers/ferguson'),
      get<Document[]>(`/api/projects/${projectId}/documents`),
      get<LineItemGroup[]>(`/api/projects/${projectId}/line-items`),
      get<Quote[]>(`/api/projects/${projectId}/quotes`),
      get<Comparison>(`/api/projects/${projectId}/packages/${pkg}/comparison`),
      get<Rfq[]>(`/api/projects/${projectId}/rfqs`),
      get<RfqFolder[]>(`/api/projects/${projectId}/rfq-folders`),
      get<Timeline>(`/api/projects/${projectId}/timeline`),
    ])

  return {
    metrics: dashboard.metrics,
    activity: dashboard.activity,
    projects,
    overviewCards: detail.overviewCards,
    packages: detail.packages,
    suppliers,
    supplierComms: supplierDetail.comms,
    docs,
    lineItems,
    quotes,
    comparison: { suppliers: comparison.suppliers, rows: comparison.rows },
    rfqs,
    rfqFolders,
    milestones: timeline.milestones,
    gantt: timeline.gantt,
    ganttCols: timeline.ganttCols,
  }
}
