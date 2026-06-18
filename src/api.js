// Thin client for the ProcureAI FastAPI backend. Returns the raw data bundle
// that buildModel() consumes; the model decorates it with styles. If the API is
// unavailable, callers fall back to the literals baked into model.js.
const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function get(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${path} -> ${res.status}`)
  return res.json()
}

export function post(path, body) {
  return fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => {
    if (!r.ok) throw new Error(`${path} -> ${r.status}`)
    return r.json()
  })
}

// ------------------------------------------------------- document extraction
// Plan types the backend extractor supports (drives the upload selector).
export function getPlanTypes() {
  return get('/api/documents/plan-types')
}

// Upload a plan set; the backend creates the doc in 'Processing' and runs
// GPT-4.1 vision extraction in the background. Returns the new Document.
export function uploadDocument(file, planType, projectId) {
  const form = new FormData()
  form.append('file', file)
  if (planType) form.append('plan_type', planType)
  if (projectId) form.append('project_id', projectId)
  return fetch(`${BASE}/api/documents`, { method: 'POST', body: form }).then((r) => {
    if (!r.ok) throw new Error(`upload -> ${r.status}`)
    return r.json()
  })
}

// BOM groups extracted from a single document.
export function getDocumentLineItems(docId) {
  return get(`/api/documents/${docId}/line-items`)
}

// Human-in-the-loop: save a reviewer's edited BOM (full replacement of groups).
export function saveDocumentLineItems(docId, groups) {
  return fetch(`${BASE}/api/documents/${docId}/line-items`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ groups }),
  }).then((r) => {
    if (!r.ok) throw new Error(`save line-items -> ${r.status}`)
    return r.json()
  })
}

// Human-in-the-loop: mark a document's BOM as reviewed/approved.
export function confirmDocument(docId) {
  return post(`/api/documents/${docId}/confirm`)
}

// Fetches everything the current single-project prototype renders, in parallel,
// and reshapes it into the keys buildModel() expects.
export async function loadModelData(projectId = 'riverside') {
  const pkg = encodeURIComponent('Water Utilities')
  const [dashboard, projects, detail, suppliers, supplierDetail, docs, lineItems, quotes, comparison, rfqs, rfqFolders, timeline] =
    await Promise.all([
      get('/api/dashboard'),
      get('/api/projects'),
      get(`/api/projects/${projectId}`),
      get('/api/suppliers'),
      get('/api/suppliers/ferguson'),
      get(`/api/projects/${projectId}/documents`),
      get(`/api/projects/${projectId}/line-items`),
      get(`/api/projects/${projectId}/quotes`),
      get(`/api/projects/${projectId}/packages/${pkg}/comparison`),
      get(`/api/projects/${projectId}/rfqs`),
      get(`/api/projects/${projectId}/rfq-folders`),
      get(`/api/projects/${projectId}/timeline`),
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
