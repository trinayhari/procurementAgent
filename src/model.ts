import type { CSSProperties } from 'react'
import { tone, badge, chip, bar, ic, lb } from './lib'
import { post } from './api'
import type { ModelData, PlanType, LineItemGroup } from './api'

// ---- App state threaded through buildModel (held in App.tsx's useState) ----
export interface State {
  nav: string
  tab: string
  compare: boolean
  docIdx: number
  rfqIdx: number
  supplierId: string | null
  theme: string
  vw: number
  mnav: boolean
  data: ModelData | null
  planTypes: PlanType[] | null
  planType: string
  uploading: boolean
  uploadError: string | null
  docLineItems: { id: string; groups: LineItemGroup[] } | null
  editBom: boolean
  bomDraft: LineItemGroup[] | null
  bomBusy: boolean
  projectId?: string
  newProjOpen?: boolean
  customProjects?: ProjectInput[]
}

export type Setter = (patch: Partial<State>) => void

// Form payload from the New project modal.
export interface ProjectForm {
  name: string
  loc: string
  value: string
  stage?: string
}

// Props passed from App.tsx (API data + human-in-the-loop callbacks).
export interface ModelProps {
  accent?: string
  data?: ModelData | null
  reload?: (pid?: string) => Promise<void> | void
  planTypes?: PlanType[] | null
  planType?: string
  uploading?: boolean
  uploadError?: string | null
  docLineItems?: { id: string; groups: LineItemGroup[] } | null
  onUpload?: (file: File) => void
  editBom?: boolean
  bomDraft?: LineItemGroup[] | null
  bomBusy?: boolean
  startBomEdit?: () => void
  cancelBomEdit?: () => void
  editBomItem?: (gi: number, ii: number, field: string, value: string) => void
  addBomItem?: (gi: number) => void
  deleteBomItem?: (gi: number, ii: number) => void
  saveBom?: () => void
  confirmBom?: () => void
}

// Loosely-typed shapes for the baked-in fallback literals. Fields that vary
// between rows are optional so the literals type-check, while the (stricter)
// generated API payloads remain assignable to them.
interface ProjectInput {
  id: string; name: string; loc: string; stage: string; stageTone: string
  value: string; progress: number; suppliers: number; rfqs: number; quotes: number
  risk: string; riskTone: string; barColor: string
}
interface MetricInput { label: string; value: string; delta: string; sub?: string; up?: boolean; down?: boolean; ai?: boolean; risk?: boolean }
interface OverviewCardInput { label: string; value: string; sub: string; icon: string; tone: string; ai?: boolean }
interface DocInput {
  id?: string; name: string; type: string; date: string; status: string; statusTone: string
  items: string; pages: number; processing?: boolean
  reviewed?: boolean; reviewedAt?: string | null; summary?: string | null; edited?: boolean
}
interface QuoteInput { sup: string; pkg: string; amount: string; freight: string; total: string; lead: string; date: string; logo: string; logoBg: string; best?: boolean }
interface CmpRowInput { label: string; vals: string[]; best: number; emph?: boolean }
interface ThreadInput { dir: string; who: string; initials: string; time: string; body: string; subject?: string; attach?: string; logoBg?: string }
interface MilestoneInput { name: string; date: string; status: string; desc: string; tone: string; done?: boolean; active?: boolean }
interface GanttInput { name: string; start: number; len: number; tone: string; label: string; warn?: boolean }

// Identity helper that contextually types an inline object literal as
// CSSProperties (so string values like 'flex' narrow to the proper unions).
const sx = (o: CSSProperties): CSSProperties => o

export type Model = ReturnType<typeof buildModel>

// Mirrors the design prototype's renderVals() — builds every computed value the
// screens consume from the current state. `s` is state, `set` merges state.
export function buildModel(s: State, set: Setter, props?: ModelProps) {
  // Raw data fetched from the backend (see src/api.ts). Each section below falls
  // back to its baked-in literal when a key is absent, so the UI renders fully
  // even if the API is unavailable.
  const D: Partial<ModelData> = (props && props.data) || {}
  const go = (n: string) => set({ nav: n, mnav: false, compare: false, supplierId: null })
  const setTab = (t: string) => set({ tab: t, compare: false, supplierId: null })

  const desktop = s.vw > 860
  const isProject = s.nav === 'project'

  const navStyleFor = (key: string): CSSProperties => {
    const active = s.nav === key || (key === 'projects' && isProject)
    return {
      display: 'flex', alignItems: 'center', gap: 11, width: '100%', padding: '8px 11px',
      borderRadius: 9, fontSize: 13.5, fontWeight: active ? 600 : 500,
      color: active ? 'var(--text)' : 'var(--text-2)',
      background: active ? 'var(--panel-3)' : 'transparent', transition: 'background .12s',
    }
  }
  const navStyle = {
    dashboard: navStyleFor('dashboard'), projects: navStyleFor('projects'),
    suppliers: navStyleFor('suppliers'), settings: navStyleFor('settings'), ds: navStyleFor('ds'),
  }

  const metricsRaw: MetricInput[] = D.metrics || [
    { label: 'Active Projects', value: '5', delta: '+2', up: true, sub: 'this quarter' },
    { label: 'Active RFQs', value: '20', delta: '+6', up: true, sub: '5 projects' },
    { label: 'Pending Quotes', value: '14', delta: '4 due soon', sub: '' },
    { label: 'Total Material Spend', value: '$35.3M', delta: '+8.1%', up: true, sub: 'committed' },
    { label: 'Potential Savings', value: '$1.84M', delta: '5.2%', up: true, sub: 'identified', ai: true },
    { label: 'Procurement Risks', value: '3', delta: '2 high', down: true, sub: 'need review', risk: true },
  ]
  const metrics = metricsRaw.map((m) => {
    let c = 'var(--text-3)'
    if (m.up) c = 'var(--success)'
    else if (m.down) c = 'var(--danger)'
    return { ...m, deltaStyle: sx({ display: 'inline-flex', alignItems: 'center', gap: 3, color: c }) }
  })

  const actRaw = D.activity || [
    { icon: 'quote', tone: 'success', title: 'Quote received from Ferguson', meta: 'Water Utilities · Riverside WTP', time: '12m' },
    { icon: 'rfq', tone: 'blue', title: 'RFQ sent to Core & Main', meta: 'Sanitary Sewer · Riverside WTP', time: '1h' },
    { icon: 'check', tone: 'success', title: 'Water Utilities package approved', meta: 'Riverside WTP · by you', time: '3h' },
    { icon: 'truck', tone: 'blue', title: 'Delivery schedule updated', meta: 'Storm Drain · Eastgate', time: '5h' },
    { icon: 'supplier', tone: 'violet', title: 'New supplier added — HD Supply', meta: 'Cedar Point Logistics Hub', time: '1d' },
    { icon: 'sparkles', tone: 'ai', title: 'AI extracted 142 line items', meta: 'Civil Site Plan Rev 3 · Riverside', time: '1d' },
  ]
  const activity = actRaw.map((a) => ({ ...a, chipStyle: chip(a.tone), iconHtml: ic(a.icon) }))

  const baseProjects: ProjectInput[] = D.projects || [
    { id: 'riverside', name: 'Riverside Water Treatment Plant', loc: 'Sacramento, CA', stage: 'RFQs Out', stageTone: 'blue', value: '$4.2M', progress: 68, suppliers: 12, rfqs: 5, quotes: 9, risk: 'Medium', riskTone: 'warn', barColor: 'var(--primary)' },
    { id: 'eastgate', name: 'Eastgate Mixed-Use Development', loc: 'Austin, TX', stage: 'Quotes In', stageTone: 'violet', value: '$8.7M', progress: 82, suppliers: 18, rfqs: 3, quotes: 14, risk: 'Low', riskTone: 'success', barColor: 'var(--violet)' },
    { id: 'hwy50', name: 'Highway 50 Interchange', loc: 'Reno, NV', stage: 'Plans Review', stageTone: 'gray', value: '$12.1M', progress: 24, suppliers: 6, rfqs: 8, quotes: 2, risk: 'High', riskTone: 'danger', barColor: 'var(--danger)' },
    { id: 'maple', name: 'Maple Grove Subdivision', loc: 'Boise, ID', stage: 'Complete', stageTone: 'success', value: '$3.4M', progress: 100, suppliers: 9, rfqs: 0, quotes: 11, risk: 'Low', riskTone: 'success', barColor: 'var(--success)' },
    { id: 'cedar', name: 'Cedar Point Logistics Hub', loc: 'Phoenix, AZ', stage: 'Sourcing', stageTone: 'blue', value: '$6.9M', progress: 45, suppliers: 11, rfqs: 4, quotes: 5, risk: 'Medium', riskTone: 'warn', barColor: 'var(--primary)' },
  ]
  // Locally-created projects (from the New project modal) overlay the seed/API
  // list so they appear instantly; they're also POSTed to the backend.
  const projRaw = [...(s.customProjects || []), ...baseProjects]
  const projectCount = projRaw.length
  const projects = projRaw.map((p) => ({
    ...p, stageBadge: badge(p.stageTone), riskBadge: badge(p.riskTone),
    barStyle: bar(p.progress, p.barColor), barTrackStyle: {},
  }))

  // ===== PROJECT WORKSPACE DATA =====
  // The open project is whichever card/row was clicked (tracked by id); fall back
  // to the first project so the workspace still renders on a fresh load.
  const activeProject = projects.find((p) => p.id === s.projectId) || projects[0] || ({
    name: 'Riverside Water Treatment Plant', loc: 'Sacramento, CA', stage: 'RFQs Out', value: '$4.2M', stageBadge: badge('blue'),
  } as (typeof projects)[number])

  const tabStyleFor = (k: string): CSSProperties => {
    const active = s.tab === k
    return {
      display: 'inline-flex', alignItems: 'center', gap: 7, padding: '13px 2px', marginRight: 20,
      fontSize: 13.5, fontWeight: active ? 600 : 500, color: active ? 'var(--text)' : 'var(--text-2)',
      borderBottom: active ? '2px solid var(--primary)' : '2px solid transparent', marginBottom: -1,
      whiteSpace: 'nowrap', background: 'none', transition: 'color .12s',
    }
  }
  const tabStyle = {
    overview: tabStyleFor('overview'), documents: tabStyleFor('documents'), suppliers: tabStyleFor('suppliers'),
    rfqs: tabStyleFor('rfqs'), quotes: tabStyleFor('quotes'), timeline: tabStyleFor('timeline'),
  }

  const overviewCards = ((D.overviewCards || [
    { label: 'Documents', value: '6', sub: '4 analyzed', icon: 'file', tone: 'blue' },
    { label: 'Suppliers Found', value: '12', sub: '6 quoted', icon: 'supplier', tone: 'violet' },
    { label: 'RFQs Sent', value: '5', sub: '3 awaiting', icon: 'rfq', tone: 'blue' },
    { label: 'Quotes Received', value: '9', sub: '2 packages', icon: 'quote', tone: 'success' },
    { label: 'Savings Identified', value: '$184K', sub: 'AI-identified', icon: 'sparkles', tone: 'ai', ai: true },
  ]) as OverviewCardInput[]).map((c) => ({ ...c, chipStyle: chip(c.tone), iconHtml: ic(c.icon) }))

  const packages = (D.packages || [
    { name: 'Water Utilities', pct: 90, tone: 'success' },
    { name: 'Sanitary Sewer', pct: 75, tone: 'blue' },
    { name: 'Storm Drain', pct: 100, tone: 'success' },
    { name: 'Electrical', pct: 40, tone: 'warn' },
  ]).map((p) => { const { fg } = tone(p.tone); return { ...p, barStyle: bar(p.pct, fg) } })

  const supRaw = D.suppliers || [
    { id: 'ferguson', name: 'Ferguson Waterworks', cats: ['Water', 'Fire'], contact: 'Mark Reyes', phone: '(916) 555-0142', email: 'mreyes@ferguson.com', web: 'ferguson.com', rfq: 'Quoted', rfqTone: 'success', last: '12m ago', quotes: '3', quoteVal: '$495.6K', lead: '14 days', logo: 'FW', logoBg: '#0a4d8c', fin: { submitted: '3', total: '$495,600', avg: '14 days' } },
    { id: 'coremain', name: 'Core & Main', cats: ['Water', 'Sewer'], contact: 'Dana Whitfield', phone: '(916) 555-0188', email: 'dwhitfield@coreandmain.com', web: 'coreandmain.com', rfq: 'Quoted', rfqTone: 'success', last: '1h ago', quotes: '2', quoteVal: '$727.2K', lead: '16 days', logo: 'C&M', logoBg: '#16a34a', fin: { submitted: '2', total: '$727,200', avg: '14 days' } },
    { id: 'fortiline', name: 'Fortiline Waterworks', cats: ['Water', 'Storm'], contact: 'Luis Romero', phone: '(775) 555-0119', email: 'lromero@fortiline.com', web: 'fortiline.com', rfq: 'Quoted', rfqTone: 'success', last: '2h ago', quotes: '1', quoteVal: '$490.7K', lead: '26 days', logo: 'FL', logoBg: '#0f766e', fin: { submitted: '1', total: '$490,700', avg: '26 days' } },
    { id: 'hdsupply', name: 'HD Supply Waterworks', cats: ['Water', 'Sewer'], contact: 'Priya Anand', phone: '(602) 555-0173', email: 'priya.anand@hdsupply.com', web: 'hdsupply.com', rfq: 'Awaiting', rfqTone: 'warn', last: 'Sent 1d ago', quotes: '0', quoteVal: '—', lead: '—', logo: 'HD', logoBg: '#b45309', fin: { submitted: '0', total: '—', avg: '—' } },
    { id: 'wesco', name: 'WESCO Distribution', cats: ['Electrical'], contact: 'Greg Tan', phone: '(916) 555-0150', email: 'gtan@wesco.com', web: 'wesco.com', rfq: 'Sent', rfqTone: 'blue', last: 'Sent 2d ago', quotes: '0', quoteVal: '—', lead: '—', logo: 'WE', logoBg: '#334155', fin: { submitted: '0', total: '—', avg: '—' } },
    { id: 'graybar', name: 'Graybar Electric', cats: ['Electrical'], contact: 'Sara Lin', phone: '(775) 555-0166', email: 'slin@graybar.com', web: 'graybar.com', rfq: 'Draft', rfqTone: 'gray', last: '—', quotes: '0', quoteVal: '—', lead: '—', logo: 'GB', logoBg: '#7c3aed', fin: { submitted: '0', total: '—', avg: '—' } },
  ]
  const suppliers = supRaw.map((x) => ({ ...x, onOpen: () => set({ supplierId: x.id }), rfqBadge: badge(x.rfqTone), logoStyle: lb(x.logoBg, 42) }))
  const supplierOpen = !!s.supplierId
  const activeSupplier = suppliers.find((x) => x.id === s.supplierId) || suppliers[0]
  const supComms = (D.supplierComms || [
    { tone: 'success', title: 'Quote submitted — Water Utilities', body: '$495,600 total · 14-day lead · Quote-RV-Water.pdf', time: 'Today · 9:42 AM', icon: 'quote' },
    { tone: 'blue', title: 'Follow-up email sent', body: 'Requested confirmation on DI pipe class and hydrant lead times.', time: 'Yesterday · 4:10 PM', icon: 'rfq' },
    { tone: 'success', title: 'Email received', body: '"We can confirm Class 350 DI. Hydrants ship in ~2 weeks." — Mark Reyes', time: 'Yesterday · 2:30 PM', icon: 'rfq' },
    { tone: 'violet', title: 'RFQ sent — Water Utilities package', body: '42 line items · due Jun 20', time: 'Jun 12 · 11:05 AM', icon: 'sparkles' },
  ]).map((c) => ({ ...c, chipStyle: chip(c.tone), iconHtml: ic(c.icon) }))

  const docRaw: DocInput[] = D.docs || [
    { name: 'Civil Site Plan — Rev 3', type: 'Civil Plans', date: 'Jun 12, 2026', status: 'Analyzed', statusTone: 'success', items: '142', pages: 24 },
    { name: 'Utility Plan — Water & Sewer', type: 'Utility Plans', date: 'Jun 11, 2026', status: 'Analyzed', statusTone: 'success', items: '88', pages: 12 },
    { name: 'Storm Drainage Plan', type: 'Civil Plans', date: 'Jun 11, 2026', status: 'Analyzed', statusTone: 'success', items: '46', pages: 8 },
    { name: 'Electrical Single-Line', type: 'Electrical Plans', date: 'Jun 10, 2026', status: 'Processing', statusTone: 'blue', items: '—', pages: 6, processing: true },
    { name: 'Project Specifications', type: 'Specifications', date: 'Jun 9, 2026', status: 'Analyzed', statusTone: 'success', items: '—', pages: 210 },
    { name: 'Addendum 02', type: 'Addenda', date: 'Jun 14, 2026', status: 'Queued', statusTone: 'gray', items: '—', pages: 4 },
  ]
  const docs = docRaw.map((d, i) => ({
    ...d, onOpen: () => set({ docIdx: i }), active: i === s.docIdx, statusBadge: badge(d.statusTone),
    rowStyle: sx({
      display: 'grid', gridTemplateColumns: 'minmax(150px,2fr) 124px 116px 104px', gap: 10,
      padding: '12px 16px', alignItems: 'center', cursor: 'pointer', borderBottom: '1px solid var(--border)',
      background: i === s.docIdx ? 'var(--primary-softer)' : 'transparent',
    }),
  }))
  const doc = docs[s.docIdx]

  // Per-document BOM groups (props.docLineItems, fetched when a doc is selected)
  // take precedence; then the project-wide line items; then baked-in literals.
  const dli = props && props.docLineItems
  const perDoc = dli && doc && dli.id === doc.id ? dli.groups : null
  const extracted = (perDoc || D.lineItems || [
    { group: 'Water Materials', count: 42, tone: 'blue', items: [{ n: '12" DI Pipe, Class 350', q: '2,400 LF' }, { n: '12" Gate Valve, RW', q: '8 EA' }, { n: 'Fire Hydrant Assembly', q: '6 EA' }, { n: '12" MJ Tee', q: '14 EA' }, { n: '12" 45° MJ Bend', q: '22 EA' }] },
    { group: 'Sewer Materials', count: 31, tone: 'violet', items: [{ n: '8" PVC SDR-35', q: '3,200 LF' }, { n: '48" Dia. Manhole', q: '14 EA' }, { n: '6" PVC Lateral', q: '1,100 LF' }, { n: 'Frame & Cover', q: '14 EA' }] },
    { group: 'Storm Materials', count: 46, tone: 'success', items: [{ n: '24" RCP, Class III', q: '1,800 LF' }, { n: 'Type A Catch Basin', q: '22 EA' }, { n: '18" RCP', q: '900 LF' }, { n: 'Storm Manhole', q: '9 EA' }] },
    { group: 'Electrical Materials', count: 23, tone: 'warn', items: [{ n: '4" PVC Conduit, Sch 40', q: '5,000 LF' }, { n: '#2 AWG Cu Conductor', q: '12,000 LF' }, { n: 'Pull Box, 24×36', q: '12 EA' }] },
  ]).map((g) => {
    const { fg } = tone(g.tone)
    return { ...g, dotStyle: sx({ width: 8, height: 8, borderRadius: 2, background: fg, flex: 'none' }), countBadge: badge(g.tone, { fontSize: 11, padding: '1px 8px' }) }
  })

  const quotes = ((D.quotes || [
    { sup: 'Ferguson Waterworks', pkg: 'Water Utilities', amount: '$487,200', freight: '$8,400', total: '$495,600', lead: '14 days', date: 'Jun 14', logo: 'FW', logoBg: '#0a4d8c', best: true },
    { sup: 'Core & Main', pkg: 'Water Utilities', amount: '$502,800', freight: '$6,200', total: '$509,000', lead: '16 days', date: 'Jun 13', logo: 'C&M', logoBg: '#16a34a' },
    { sup: 'Fortiline Waterworks', pkg: 'Water Utilities', amount: '$478,900', freight: '$11,800', total: '$490,700', lead: '26 days', date: 'Jun 15', logo: 'FL', logoBg: '#0f766e' },
    { sup: 'Core & Main', pkg: 'Sanitary Sewer', amount: '$214,300', freight: '$3,900', total: '$218,200', lead: '12 days', date: 'Jun 13', logo: 'C&M', logoBg: '#16a34a' },
    { sup: 'HD Supply Waterworks', pkg: 'Sanitary Sewer', amount: '$221,750', freight: '$2,800', total: '$224,550', lead: '10 days', date: 'Jun 16', logo: 'HD', logoBg: '#b45309' },
  ]) as QuoteInput[]).map((q) => ({ ...q, onOpen: () => set({ compare: true }), logoStyle: lb(q.logoBg, 30) }))

  const cmpSup = ((D.comparison && D.comparison.suppliers) || [
    { name: 'Ferguson Waterworks', logo: 'FW', logoBg: '#0a4d8c', rec: true },
    { name: 'Core & Main', logo: 'C&M', logoBg: '#16a34a', rec: false },
    { name: 'Fortiline Waterworks', logo: 'FL', logoBg: '#0f766e', rec: false },
  ]).map((c) => ({ ...c, logoStyle: lb(c.logoBg, 40) }))
  const cmpRowsRaw: CmpRowInput[] = (D.comparison && D.comparison.rows) || [
    { label: 'Material Cost', vals: ['$487,200', '$502,800', '$478,900'], best: 2 },
    { label: 'Freight', vals: ['$8,400', '$6,200', '$11,800'], best: 1 },
    { label: 'Total Cost', vals: ['$495,600', '$509,000', '$490,700'], best: 2, emph: true },
    { label: 'Lead Time', vals: ['14 days', '16 days', '26 days'], best: 0 },
    { label: 'Delivery Date', vals: ['Jul 4', 'Jul 6', 'Jul 16'], best: 0 },
    { label: 'Risk Score', vals: ['94 · Low', '88 · Low', '69 · Med'], best: 0 },
  ]
  const cmpRows = cmpRowsRaw.map((r) => ({
    ...r, emph: !!r.emph,
    cells: r.vals.map((v, i) => {
      const best = i === r.best
      return {
        v, best,
        style: sx({
          flex: 1, textAlign: 'center', padding: '14px 10px', fontFamily: "'JetBrains Mono',monospace",
          fontSize: r.emph ? 16 : 13.5, fontWeight: best ? 700 : r.emph ? 600 : 500,
          color: best ? 'var(--success)' : 'var(--text)', background: best ? 'var(--success-soft)' : 'transparent',
          borderRadius: best ? 9 : 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
        }),
      }
    }),
  }))
  const cmp = { suppliers: cmpSup, rows: cmpRows }

  const rfqRaw = D.rfqs || [
    { sup: 'Ferguson Waterworks', pkg: 'Water Utilities', folder: 'Completed', status: 'Quoted', statusTone: 'success', preview: 'Quote attached — $495,600 · 14-day lead', time: '12m', unread: false, logo: 'FW', logoBg: '#0a4d8c' },
    { sup: 'Core & Main', pkg: 'Sanitary Sewer', folder: 'Awaiting', status: 'Awaiting', statusTone: 'warn', preview: 'RFQ sent — awaiting response', time: '1h', unread: true, logo: 'C&M', logoBg: '#16a34a' },
    { sup: 'Fortiline Waterworks', pkg: 'Storm Drain', folder: 'Awaiting', status: 'Awaiting', statusTone: 'warn', preview: 'Follow-up scheduled for Jun 18', time: '2h', unread: false, logo: 'FL', logoBg: '#0f766e' },
    { sup: 'WESCO Distribution', pkg: 'Electrical', folder: 'Sent', status: 'Sent', statusTone: 'blue', preview: 'RFQ sent — 23 line items', time: '2d', unread: false, logo: 'WE', logoBg: '#334155' },
    { sup: 'Graybar Electric', pkg: 'Electrical', folder: 'Draft', status: 'Draft', statusTone: 'gray', preview: 'Draft — not yet sent', time: '—', unread: false, logo: 'GB', logoBg: '#7c3aed' },
  ]
  const rfqs = rfqRaw.map((r, i) => ({
    ...r, onSelect: () => set({ rfqIdx: i }), active: i === s.rfqIdx, statusBadge: badge(r.statusTone),
    rowStyle: sx({
      display: 'flex', gap: 11, padding: '13px 15px', cursor: 'pointer', borderBottom: '1px solid var(--border)',
      borderLeft: i === s.rfqIdx ? '2px solid var(--primary)' : '2px solid transparent',
      background: i === s.rfqIdx ? 'var(--primary-softer)' : 'transparent',
    }),
    logoStyle: lb(r.logoBg, 34),
  }))
  const rfqSel = rfqs[s.rfqIdx]
  const rfqFolders = D.rfqFolders || [{ name: 'Draft', count: '1' }, { name: 'Sent', count: '1' }, { name: 'Awaiting Response', count: '2' }, { name: 'Completed', count: '1' }]
  const thread = ([
    { dir: 'out', who: 'You · ProcureAI', initials: 'JM', time: 'Jun 12 · 11:05 AM', subject: 'RFQ: ' + rfqSel.pkg + ' — Riverside WTP', body: 'Please find attached our request for quote covering the ' + rfqSel.pkg + ' package for the Riverside Water Treatment Plant. 42 line items, quotes due Jun 20. Let us know if any specs need clarification.', attach: 'RFQ-Riverside-Water.pdf' },
    { dir: 'in', who: rfqSel.sup, initials: rfqSel.logo, logoBg: rfqSel.logoBg, time: 'Jun 13 · 2:30 PM', body: 'Thanks — reviewing now. Can you confirm the DI pipe class on line item 4?' },
    { dir: 'out', who: 'You · ProcureAI', initials: 'JM', time: 'Jun 13 · 3:10 PM', body: 'Class 350 per spec section 02510. Appreciate the quick turnaround.' },
    { dir: 'in', who: rfqSel.sup, initials: rfqSel.logo, logoBg: rfqSel.logoBg, time: 'Today · 9:42 AM', body: 'Quote attached. Total comes to $495,600 with a 14-day lead time. Hydrant assemblies ship in ~2 weeks.', attach: 'Quote-RV-Water.pdf' },
  ] as ThreadInput[]).map((t) => ({
    ...t, isOut: t.dir === 'out', isIn: t.dir === 'in', hasAttach: !!t.attach, hasSubject: !!t.subject,
    avatarStyle: sx({
      width: 30, height: 30, borderRadius: '50%', flex: 'none', display: 'flex', alignItems: 'center',
      justifyContent: 'center', fontSize: 11, fontWeight: 600, color: '#fff',
      background: t.dir === 'out' ? 'linear-gradient(135deg,#2563eb,#7c3aed)' : t.logoBg || '#334155',
    }),
  }))

  const milestones = ((D.milestones || [
    { name: 'Documents Uploaded', date: 'Jun 9', status: 'Done', desc: '6 plan sets ingested', tone: 'success', done: true },
    { name: 'AI Extraction Complete', date: 'Jun 12', status: 'Done', desc: '307 line items · 4 packages', tone: 'success', done: true },
    { name: 'RFQs Generated', date: 'Jun 13', status: 'Done', desc: '5 packages → 12 suppliers', tone: 'success', done: true },
    { name: 'Quotes Received', date: 'Due Jun 20', status: 'In Progress', desc: '9 of 14 received', tone: 'blue', active: true },
    { name: 'Supplier Selected', date: 'Jun 24', status: 'Upcoming', desc: 'Water decision ready', tone: 'gray' },
    { name: 'Purchase Order Issued', date: 'Jun 27', status: 'Upcoming', desc: 'Pending selection', tone: 'gray' },
    { name: 'Delivery Scheduled', date: 'Jul 4', status: 'Upcoming', desc: 'Water materials on-site', tone: 'gray' },
  ]) as MilestoneInput[]).map((m) => ({
    ...m, statusBadge: badge(m.tone),
    dotStyle: sx({
      width: 13, height: 13, borderRadius: '50%', flex: 'none', border: '2px solid var(--panel)',
      boxShadow: '0 0 0 2px ' + (m.done ? 'var(--success)' : m.active ? 'var(--primary)' : 'var(--border-strong)'),
      background: m.done ? 'var(--success)' : m.active ? 'var(--primary)' : 'var(--panel-2)',
    }),
  }))

  const gantt = ((D.gantt || [
    { name: 'Documents & Extraction', start: 0, len: 18, tone: 'success', label: 'Done' },
    { name: 'Water Utilities RFQ', start: 14, len: 26, tone: 'success', label: 'Quoted' },
    { name: 'Sanitary Sewer RFQ', start: 22, len: 30, tone: 'blue', label: 'In progress' },
    { name: 'Storm Drain RFQ', start: 26, len: 36, tone: 'warn', label: 'Delayed', warn: true },
    { name: 'Electrical RFQ', start: 36, len: 30, tone: 'gray', label: 'Sent' },
    { name: 'Water Delivery', start: 64, len: 14, tone: 'violet', label: 'Jul 4' },
  ]) as GanttInput[]).map((g) => {
    const { fg } = tone(g.tone)
    return {
      ...g,
      barStyle: sx({
        position: 'absolute', left: g.start + '%', width: g.len + '%', top: 7, bottom: 7, borderRadius: 7,
        background: fg, display: 'flex', alignItems: 'center', padding: '0 10px',
        color: g.tone === 'gray' ? 'var(--text)' : '#fff', fontSize: 11, fontWeight: 600,
        whiteSpace: 'nowrap', overflow: 'hidden', boxShadow: 'var(--shadow-sm)',
      }),
    }
  })
  const ganttCols = D.ganttCols || ['Jun W2', 'Jun W3', 'Jun W4', 'Jul W1', 'Jul W2']

  let crumbMain = 'Dashboard', crumbSub = '', hasSub = false
  if (s.nav === 'projects') crumbMain = 'Projects'
  else if (s.nav === 'suppliers') crumbMain = 'Suppliers'
  else if (s.nav === 'settings') crumbMain = 'Settings'
  else if (s.nav === 'ds') crumbMain = 'Design System'
  else if (isProject) { crumbMain = 'Projects'; crumbSub = activeProject.name; hasSub = true }

  return {
    theme: s.theme, accent: (props && props.accent) || 'blue', isDark: s.theme === 'dark', isLight: s.theme !== 'dark',
    desktop, mobile: !desktop, navStyle,
    isDashboard: s.nav === 'dashboard', isProjects: s.nav === 'projects', isSuppliers: s.nav === 'suppliers',
    isSettings: s.nav === 'settings', isDS: s.nav === 'ds', isProject,
    crumbMain, crumbSub, hasSub,
    metrics, activity, projects, projectCount,
    newProjOpen: !!s.newProjOpen,
    openNewProject: () => set({ newProjOpen: true }),
    closeNewProject: () => set({ newProjOpen: false }),
    createProject: async (form: ProjectForm) => {
      const stageToneMap: Record<string, string> = {
        'Plans Review': 'gray', Sourcing: 'blue', 'RFQs Out': 'blue',
        'Quotes In': 'violet', Complete: 'success',
      }
      const stage = form.stage || 'Plans Review'
      // Optimistic project so the workspace opens instantly; reconciled with the
      // persisted record (real id) once the backend responds.
      const temp = {
        id: 'proj-' + Date.now(), name: form.name.trim(), loc: form.loc.trim() || '—',
        stage, stageTone: stageToneMap[stage] || 'gray', value: form.value.trim() || '$0',
        progress: 0, suppliers: 0, rfqs: 0, quotes: 0, risk: 'Low', riskTone: 'success',
        barColor: 'var(--primary)',
      }
      set({
        customProjects: [temp, ...(s.customProjects || [])], newProjOpen: false,
        nav: 'project', projectId: temp.id, tab: 'overview', compare: false, supplierId: null, mnav: false,
      })
      try {
        const saved = await post<{ id: string }>('/api/projects', { name: temp.name, loc: form.loc.trim(), value: form.value.trim(), stage })
        // Now persisted: refetch the project list and drop the optimistic copy,
        // keeping the workspace pinned to the saved project's real id.
        if (props && props.reload) await props.reload()
        set({ customProjects: (s.customProjects || []).filter((p) => p.id !== temp.id), projectId: saved.id })
      } catch {
        // Backend unavailable — keep the optimistic project so the UI still works.
      }
    },
    goDashboard: () => go('dashboard'), goProjects: () => go('projects'),
    goSuppliers: () => go('suppliers'), goSettings: () => go('settings'), goDS: () => go('ds'),
    openProject: (p?: { id?: string }) => set({ nav: 'project', projectId: (p && p.id) || s.projectId, tab: 'overview', compare: false, supplierId: null, mnav: false }),
    toggleTheme: () => set({ theme: s.theme === 'dark' ? 'light' : 'dark' }),
    toggleMnav: () => set({ mnav: !s.mnav }),
    mnavOpen: s.mnav, closeMnav: () => set({ mnav: false }),
    activeProject, tabStyle,
    tabOverview: s.tab === 'overview', tabDocuments: s.tab === 'documents', tabSuppliers: s.tab === 'suppliers',
    tabRfqs: s.tab === 'rfqs', tabQuotesTable: s.tab === 'quotes' && !s.compare, tabCompare: s.tab === 'quotes' && s.compare, tabTimeline: s.tab === 'timeline',
    overviewCards, packages,
    suppliers, supplierOpen, activeSupplier, supComms,
    docs, doc, extracted,
    // Upload / extraction wiring (see App.tsx + TabDocuments).
    planTypes: (props && props.planTypes) || null,
    planType: (props && props.planType) || 'site_plan',
    setPlanType: (key: string) => set({ planType: key }),
    uploading: !!(props && props.uploading),
    uploadError: (props && props.uploadError) || null,
    onUpload: props?.onUpload ?? ((_file: File) => {}),
    // Human-in-the-loop BOM review (see App.tsx + ExtractedPanel).
    bomEditing: !!(props && props.editBom),
    bomDraft: (props && props.bomDraft) || [],
    bomBusy: !!(props && props.bomBusy),
    startBomEdit: (props && props.startBomEdit) || (() => {}),
    cancelBomEdit: (props && props.cancelBomEdit) || (() => {}),
    editBomItem: props?.editBomItem ?? ((_gi: number, _ii: number, _field: string, _value: string) => {}),
    addBomItem: props?.addBomItem ?? ((_gi: number) => {}),
    deleteBomItem: props?.deleteBomItem ?? ((_gi: number, _ii: number) => {}),
    saveBom: (props && props.saveBom) || (() => {}),
    confirmBom: (props && props.confirmBom) || (() => {}),
    quotes, cmp, rfqs, rfqSel, rfqFolders, thread, milestones, gantt, ganttCols,
    setOverview: () => setTab('overview'), setDocuments: () => setTab('documents'), setSuppliers: () => setTab('suppliers'),
    setRfqs: () => setTab('rfqs'), setQuotes: () => setTab('quotes'), setTimeline: () => setTab('timeline'),
    openCompare: () => set({ compare: true }), closeCompare: () => set({ compare: false }),
    closeSupplier: () => set({ supplierId: null }),
    badgeBlue: badge('blue'), badgeSuccess: badge('success'), badgeWarn: badge('warn'),
    badgeDanger: badge('danger'), badgeViolet: badge('violet'), badgeGray: badge('gray'),
  }
}
