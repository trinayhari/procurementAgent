import type { CSSProperties } from 'react'
import { tone, badge, chip, bar, ic, lb } from './lib'
import { post, deleteProject as apiDeleteProject, deleteSupplier as apiDeleteSupplier } from './api'
import type { ModelData, PlanType, LineItemGroup, AuthUser } from './api'

// ---- App state threaded through buildModel (held in App.tsx's useState) ----
export interface State {
  nav: string
  tab: string
  compare: boolean
  docIdx: number
  rfqIdx: number
  supplierId: string | null
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
  comparePkg?: string
  newProjOpen?: boolean
  customProjects?: ProjectInput[]
  projError?: string | null
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
  user?: AuthUser | null
  onLogout?: () => void
  onUserUpdated?: (u: AuthUser) => void
  reload?: (pid?: string) => Promise<unknown> | void
  planTypes?: PlanType[] | null
  planType?: string
  uploading?: boolean
  uploadError?: string | null
  docLineItems?: { id: string; groups: LineItemGroup[] } | null
  onUpload?: (file: File, planType?: string) => void
  onDeleteDoc?: (id: string) => void
  onCreateBom?: () => void
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
  items: string; pages: number; processing?: boolean; hasFile?: boolean; planType?: string | null
  reviewed?: boolean; reviewedAt?: string | null; summary?: string | null; edited?: boolean
  timelineEvents?: number
}
interface QuoteInput { id?: string; sup: string; pkg: string; amount: string; freight: string; total: string; lead: string; date: string; logo: string; logoBg: string; best?: boolean }
interface CmpRowInput { label: string; vals: string[]; best: number; emph?: boolean }
interface ThreadInput { dir: string; who: string; initials: string; time: string; body: string; subject?: string; attach?: string; logoBg?: string }
interface MilestoneInput { id?: number | null; name: string; date: string; status: string; desc: string; tone: string; done?: boolean; active?: boolean; conflict?: boolean }
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

  // ---- Signed-in user (from /api/auth/me; falls back to a friendly default) ----
  const authUser = (props && props.user) || null
  const userName = (authUser && authUser.name) || 'there'
  const userCompany = (authUser && authUser.company) || ''
  const userEmail = (authUser && authUser.email) || ''
  const firstName = userName.split(' ')[0]
  const userInitials =
    userName
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0])
      .join('')
      .toUpperCase() || 'U'
  // Time-of-day greeting (the prototype hard-coded "Good afternoon").
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'

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
    suppliers: navStyleFor('suppliers'), settings: navStyleFor('settings'),
  }

  const metricsRaw: MetricInput[] = D.metrics || []
  const metrics = metricsRaw.map((m) => {
    let c = 'var(--text-3)'
    if (m.up) c = 'var(--success)'
    else if (m.down) c = 'var(--danger)'
    return { ...m, deltaStyle: sx({ display: 'inline-flex', alignItems: 'center', gap: 3, color: c }) }
  })

  const actRaw = D.activity || []
  const activity = actRaw.map((a) => ({ ...a, chipStyle: chip(a.tone), iconHtml: ic(a.icon) }))

  // Per-project event stream (real activity logged as the user works a project),
  // distinct from the global dashboard `activity` feed above.
  const projActRaw = D.projectActivity || []
  const projectActivity = projActRaw.map((a) => ({ ...a, chipStyle: chip(a.tone), iconHtml: ic(a.icon) }))

  const baseProjects: ProjectInput[] = D.projects || []
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
    id: '', name: '', loc: '', stage: '', value: '', stageBadge: badge('gray'),
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

  const overviewCards = ((D.overviewCards || []) as OverviewCardInput[]).map((c) => ({ ...c, chipStyle: chip(c.tone), iconHtml: ic(c.icon) }))

  const packages = (D.packages || []).map((p) => { const { fg } = tone(p.tone); return { ...p, barStyle: bar(p.pct, fg) } })

  const supRaw = D.suppliers || []
  const suppliers = supRaw.map((x) => ({ ...x, onOpen: () => set({ supplierId: x.id }), rfqBadge: badge(x.rfqTone), logoStyle: lb(x.logoBg, 42) }))
  const supplierOpen = !!s.supplierId
  const activeSupplier = suppliers.find((x) => x.id === s.supplierId) || suppliers[0]
  const supComms = (D.supplierComms || []).map((c) => ({ ...c, chipStyle: chip(c.tone), iconHtml: ic(c.icon) }))

  const docRaw: DocInput[] = D.docs || []
  const docs = docRaw.map((d, i) => ({
    ...d, onOpen: () => set({ docIdx: i }), active: i === s.docIdx, statusBadge: badge(d.statusTone),
    rowStyle: sx({
      display: 'grid', gridTemplateColumns: 'minmax(150px,2fr) 124px 116px 104px', gap: 10,
      padding: '12px 16px', alignItems: 'center', cursor: 'pointer', borderBottom: '1px solid var(--border)',
      background: i === s.docIdx ? 'var(--primary-softer)' : 'transparent',
    }),
  }))
  const doc = docs[s.docIdx]

  // ---- Plan slots: one site / building / electrical plan each, plus a list of
  // additional reference documents. Each slot is filled by the (single) document
  // whose planType matches; re-uploading replaces it on the backend.
  const SLOT_KEYS = ['site_plan', 'building_plan', 'electrical_plan']
  const planTypeList = (props && props.planTypes) || []
  const specFor = (key: string) => planTypeList.find((t) => t.key === key)
  const docSlots = SLOT_KEYS.map((key) => {
    const spec = specFor(key)
    return {
      key,
      label: (spec && spec.label) || key,
      description: (spec && spec.description) || '',
      enabled: spec ? spec.enabled : true,
      categories: (spec && spec.categories) || [],
      doc: docs.find((d) => d.planType === key) || null,
    }
  })
  // Hand-built custom BOMs (created in the Documents panel, no upload/extraction).
  // They render in their own section and are selectable as packages in sourcing.
  const CUSTOM_BOM_TYPE = 'custom_bom'
  const customBoms = docs.filter((d) => d.planType === CUSTOM_BOM_TYPE)
  // Everything not occupying a plan slot and not a custom BOM (planType 'other',
  // or legacy/seed docs with no planType) is an additional reference document.
  const additionalDocs = docs.filter(
    (d) => !SLOT_KEYS.includes((d.planType as string) || '') && d.planType !== CUSTOM_BOM_TYPE,
  )
  const additionalSpec = specFor('other')

  // Per-document BOM groups (props.docLineItems, fetched when a doc is selected)
  // take precedence; then the project-wide line items; then baked-in literals.
  const dli = props && props.docLineItems
  const perDoc = dli && doc && dli.id === doc.id ? dli.groups : null
  const extracted = (perDoc || D.lineItems || []).map((g) => {
    const { fg } = tone(g.tone)
    return { ...g, dotStyle: sx({ width: 8, height: 8, borderRadius: 2, background: fg, flex: 'none' }), countBadge: badge(g.tone, { fontSize: 11, padding: '1px 8px' }) }
  })

  const quotes = ((D.quotes || []) as QuoteInput[]).map((q) => ({ ...q, onOpen: () => set({ compare: true, comparePkg: q.pkg }), logoStyle: lb(q.logoBg, 30) }))

  const cmpSup = ((D.comparison && D.comparison.suppliers) || []).map((c) => ({ ...c, logoStyle: lb(c.logoBg, 40) }))
  const cmpRowsRaw: CmpRowInput[] = (D.comparison && D.comparison.rows) || []
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
  const cmpMeta = D.comparison || ({} as NonNullable<typeof D.comparison>)
  const recName = cmpMeta.recommendation || (cmpSup.find((c) => c.rec) || {}).name || ''
  const recSup = cmpSup.find((c) => c.name === recName) || cmpSup.find((c) => c.rec) || cmpSup[0]
  const recQuote = quotes.find((q) => q.sup === recName)
  const cmp = {
    suppliers: cmpSup,
    rows: cmpRows,
    recommendation: recName,
    recReasons: (cmpMeta.reasons && cmpMeta.reasons.length ? cmpMeta.reasons : []),
    savings: cmpMeta.savings || '',
    savingsNote: cmpMeta.savingsNote || '',
    recLogo: recSup ? recSup.logo : '',
    recLogoStyle: recSup ? recSup.logoStyle : lb('#334155', 40),
    recQuoteId: recQuote ? recQuote.id : undefined,
  }

  const rfqRaw = D.rfqs || []
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
  const rfqFolders = D.rfqFolders || []
  const thread = (!rfqSel ? [] : [
    { dir: 'out', who: 'You · Proq', initials: 'JM', time: 'Jun 12 · 11:05 AM', subject: 'RFQ: ' + rfqSel.pkg + ' — Riverside WTP', body: 'Please find attached our request for quote covering the ' + rfqSel.pkg + ' package for the Riverside Water Treatment Plant. Quotes due Jun 20. Let us know if any specs need clarification.', attach: 'RFQ-Riverside-' + rfqSel.pkg.split(' ')[0] + '.pdf' },
    { dir: 'in', who: rfqSel.sup, initials: rfqSel.logo, logoBg: rfqSel.logoBg, time: 'Jun 13 · 2:30 PM', body: 'Thanks — reviewing now. Can you confirm specs on the priced line items?' },
    { dir: 'out', who: 'You · Proq', initials: 'JM', time: 'Jun 13 · 3:10 PM', body: 'Confirmed per spec section 02510. Appreciate the quick turnaround.' },
    { dir: 'in', who: rfqSel.sup, initials: rfqSel.logo, logoBg: rfqSel.logoBg, time: 'Today · 9:42 AM', body: 'Quote attached — ' + rfqSel.preview.replace('Quote attached — ', '') + '.', attach: 'Quote-RV-' + rfqSel.pkg.split(' ')[0] + '.pdf' },
  ] as ThreadInput[]).map((t) => ({
    ...t, isOut: t.dir === 'out', isIn: t.dir === 'in', hasAttach: !!t.attach, hasSubject: !!t.subject,
    avatarStyle: sx({
      width: 30, height: 30, borderRadius: '50%', flex: 'none', display: 'flex', alignItems: 'center',
      justifyContent: 'center', fontSize: 11, fontWeight: 600, color: '#fff',
      background: t.dir === 'out' ? 'linear-gradient(135deg,#2563eb,#7c3aed)' : t.logoBg || '#334155',
    }),
  }))

  const milestones = ((D.milestones || []) as MilestoneInput[]).map((m) => ({
    ...m, statusBadge: badge(m.tone),
    dotStyle: sx({
      width: 13, height: 13, borderRadius: '50%', flex: 'none', border: '2px solid var(--panel)',
      boxShadow: '0 0 0 2px ' + (m.done ? 'var(--success)' : m.active ? 'var(--primary)' : 'var(--border-strong)'),
      background: m.done ? 'var(--success)' : m.active ? 'var(--primary)' : 'var(--panel-2)',
    }),
  }))

  const gantt = ((D.gantt || []) as GanttInput[]).map((g) => {
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
  const ganttCols = D.ganttCols || []

  let crumbMain = 'Dashboard', crumbSub = '', hasSub = false
  if (s.nav === 'projects') crumbMain = 'Projects'
  else if (s.nav === 'suppliers') crumbMain = 'Suppliers'
  else if (s.nav === 'settings') crumbMain = 'Settings'
  else if (isProject) { crumbMain = 'Projects'; crumbSub = activeProject.name; hasSub = true }

  return {
    accent: (props && props.accent) || 'blue',
    desktop, mobile: !desktop, navStyle,
    // Signed-in user identity + sign-out (see App.tsx Sidebar/Settings/Dashboard).
    userName, userCompany, userEmail, userInitials, firstName, greeting,
    userCcEmail: (authUser && authUser.ccEmail) || '',
    logout: (props && props.onLogout) || (() => {}),
    onUserUpdated: (props && props.onUserUpdated) || (() => {}),
    isDashboard: s.nav === 'dashboard', isProjects: s.nav === 'projects', isSuppliers: s.nav === 'suppliers',
    isSettings: s.nav === 'settings', isProject,
    crumbMain, crumbSub, hasSub,
    metrics, activity, projectActivity, projects, projectCount,
    newProjOpen: !!s.newProjOpen,
    projError: s.projError || null,
    dismissProjError: () => set({ projError: null }),
    openNewProject: () => set({ newProjOpen: true, projError: null }),
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
        set({ customProjects: (s.customProjects || []).filter((p) => p.id !== temp.id), projectId: saved.id, projError: null })
      } catch {
        // Save failed (backend unreachable or rejected). Roll the optimistic
        // project back out and surface the failure instead of silently keeping a
        // copy that only lives in memory and vanishes on the next refresh.
        set({
          customProjects: (s.customProjects || []).filter((p) => p.id !== temp.id),
          nav: 'projects', projectId: undefined, tab: 'overview', compare: false, supplierId: null,
          projError: `Couldn't save “${temp.name}” — is the backend running? Nothing was saved.`,
        })
      }
    },
    // Delete a project (and everything scoped to it). Removes any optimistic
    // local copy immediately, then deletes server-side and refetches the list.
    deleteProject: async (id: string) => {
      const wasActive = s.projectId === id
      set({ customProjects: (s.customProjects || []).filter((p) => p.id !== id) })
      try {
        await apiDeleteProject(id)
        if (props && props.reload) await props.reload()
        if (wasActive) set({ nav: 'projects', projectId: undefined, tab: 'overview', compare: false, supplierId: null, mnav: false })
      } catch {
        set({ projError: 'Couldn’t delete the project — is the backend running?' })
        if (props && props.reload) await props.reload()
      }
    },
    goDashboard: () => go('dashboard'), goProjects: () => go('projects'),
    goSuppliers: () => go('suppliers'), goSettings: () => go('settings'),
    openProject: (p?: { id?: string }) => set({ nav: 'project', projectId: (p && p.id) || s.projectId, tab: 'overview', compare: false, supplierId: null, mnav: false }),
    toggleMnav: () => set({ mnav: !s.mnav }),
    mnavOpen: s.mnav, closeMnav: () => set({ mnav: false }),
    activeProject, tabStyle,
    tabOverview: s.tab === 'overview', tabDocuments: s.tab === 'documents', tabSuppliers: s.tab === 'suppliers',
    tabRfqs: s.tab === 'rfqs', tabQuotesTable: s.tab === 'quotes' && !s.compare, tabCompare: s.tab === 'quotes' && s.compare, tabTimeline: s.tab === 'timeline',
    overviewCards, packages,
    suppliers, supplierOpen, activeSupplier, supComms,
    docs, doc, extracted,
    // Plan slots + additional documents (see App.tsx + TabDocuments).
    docSlots, additionalDocs, customBoms,
    additionalLabel: (additionalSpec && additionalSpec.label) || 'Additional Document',
    additionalKey: 'other',
    customBomType: CUSTOM_BOM_TYPE,
    createBom: (props && props.onCreateBom) || (() => {}),
    // Upload / extraction wiring (see App.tsx + TabDocuments).
    planTypes: (props && props.planTypes) || null,
    planType: (props && props.planType) || 'site_plan',
    setPlanType: (key: string) => set({ planType: key }),
    uploading: !!(props && props.uploading),
    uploadError: (props && props.uploadError) || null,
    onUpload: props?.onUpload ?? ((_file: File, _planType?: string) => {}),
    onDeleteDoc: props?.onDeleteDoc ?? ((_id: string) => {}),
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
    reload: (props && props.reload) || (async () => {}),
    setOverview: () => setTab('overview'), setDocuments: () => setTab('documents'), setSuppliers: () => setTab('suppliers'),
    setRfqs: () => setTab('rfqs'), setQuotes: () => setTab('quotes'), setTimeline: () => setTab('timeline'),
    openCompare: () => set({ compare: true }), closeCompare: () => set({ compare: false }),
    comparePackage: (pkg: string) => set({ compare: true, comparePkg: pkg }),
    projectId: s.projectId || activeProject.id || '', comparePkg: s.comparePkg || '',
    closeSupplier: () => set({ supplierId: null }),
    // Remove a supplier from the network, then refresh the directory and close
    // the drawer if the removed supplier was open.
    deleteSupplier: async (id: string) => {
      try {
        await apiDeleteSupplier(id)
        if (s.supplierId === id) set({ supplierId: null })
        if (props && props.reload) await props.reload()
      } catch {
        set({ projError: 'Couldn’t remove the supplier — is the backend running?' })
      }
    },
    badgeBlue: badge('blue'), badgeSuccess: badge('success'), badgeWarn: badge('warn'),
    badgeDanger: badge('danger'), badgeViolet: badge('violet'), badgeGray: badge('gray'),
  }
}
