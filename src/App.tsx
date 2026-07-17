import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, DragEvent, FormEvent, MouseEvent } from 'react'
import { Box, DcIcon, css, ic, lb } from './lib'
import { buildModel } from './model'
import type { Model, State } from './model'
import Login from './Login'
import {
  loadModelData, getPlanTypes, uploadDocument, getDocumentLineItems,
  saveDocumentLineItems, confirmDocument, deleteDocument, createManualBom, setTimelineEventDone,
  searchSuppliers, getFoundSuppliers, getPackageBom, generateRfq, listGeneratedRfqs, saveRfq, sendRfq, deleteRfq,
  getDocumentFileUrl, sendTestEmail,
  listProjectBoms, createSupplier,
  listLenders, createLender, deleteLender,
  getRfqConversation, ingestQuotes, getIngestStatus,
  getLineComparison, awardPackage,
  getToken, getMe, logout as apiLogout, onAuthChange, updateMe,
} from './api'
import type {
  SupplierSearchResult, FoundSupplier, PackageBom, PersistedRfq, RfqRecipient, RfqConversation,
  CustomBomSummary, LineComparison, AwardOption, AuthUser, Lender,
} from './api'

// Every screen component receives the computed model `m` from buildModel().
type MProps = { m: Model }

// A BOM group as rendered by ExtractedPanel — either a plain draft group or an
// extracted group decorated with presentational styles.
type BomGroup = {
  group: string
  count: number
  items: { n: string; q: string }[]
  dotStyle?: CSSProperties
  countBadge?: CSSProperties
}

// Small inline svg helper for the many literal icons in the markup.
// `d` may be raw element markup (starts with "<") or bare path data, which is
// wrapped in a <path>. Some constants embed extra `"/><path d="` to add paths.
function Svg({
  d,
  size = 17,
  sw = 2,
  fill = false,
  stroke = 'currentColor',
  style,
}: {
  d: string
  size?: number
  sw?: number
  fill?: boolean
  stroke?: string
  style?: CSSProperties
}) {
  const inner = d.trim().startsWith('<') ? d : `<path d="${d}" />`
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      fill={fill ? (stroke === 'currentColor' ? 'currentColor' : stroke) : 'none'}
      stroke={fill ? 'none' : stroke}
      strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={style}
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  )
}
// Icon from the ICONS map, rendered inline (matches dangerouslySetInnerHTML usage).
function IconHtml({ html, size = 15, sw = 2 }: { html: { __html: string }; size?: number; sw?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"
      dangerouslySetInnerHTML={html} />
  )
}

const SPARKLE = 'M12 2l1.7 4.6L18 8l-4.3 1.4L12 14l-1.7-4.6L6 8l4.3-1.4z'
const SPARKLE_SM = 'M12 2l1.6 4.6L18 8l-4.4 1.4L12 14l-1.6-4.6L6 8l4.4-1.4z'
const PLUS = 'M12 5v14M5 12h14'
const TRASH = 'M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m1 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6'
const CHEVRON = 'm9 6 6 6-6 6'
const PIN = 'M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z" /><circle cx="12" cy="10" r="2.6'

// ---- URL <-> navigation state ----
// We mirror the active page in the URL hash so a full reload (or a shared link,
// or back/forward) lands back where the user was, instead of resetting to the
// dashboard. Only the navigation slice is encoded; transient UI (open drawers,
// modals) is intentionally left out.
function hashFor(s: Pick<State, 'nav' | 'projectId' | 'tab' | 'compare' | 'comparePkg'>): string {
  if (s.nav === 'project' && s.projectId) {
    if (s.tab === 'quotes' && s.compare) {
      return `#/project/${s.projectId}/quotes/compare${s.comparePkg ? `/${s.comparePkg}` : ''}`
    }
    return `#/project/${s.projectId}/${s.tab || 'overview'}`
  }
  if (s.nav === 'dashboard') return '#/dashboard'
  return `#/${s.nav}`
}

function parseHash(): Partial<State> {
  const raw = (typeof window !== 'undefined' ? window.location.hash : '').replace(/^#\/?/, '')
  const seg = raw.split('/').filter(Boolean)
  if (seg[0] === 'project' && seg[1]) {
    if (seg[2] === 'quotes' && seg[3] === 'compare') {
      return { nav: 'project', projectId: seg[1], tab: 'quotes', compare: true, comparePkg: seg[4] || undefined }
    }
    return { nav: 'project', projectId: seg[1], tab: seg[2] || 'overview' }
  }
  if (['projects', 'suppliers', 'settings', 'ds', 'dashboard'].includes(seg[0])) {
    return { nav: seg[0] }
  }
  return {}
}

export default function App() {
  const [s, setS] = useState<State>({
    nav: 'dashboard', tab: 'overview', compare: false, docIdx: 0, rfqIdx: 0,
    supplierId: null, theme: 'light', vw: typeof window !== 'undefined' ? window.innerWidth : 1280, mnav: false,
    data: null,
    planTypes: null, planType: 'site_plan', uploading: false, uploadError: null, docLineItems: null,
    editBom: false, bomDraft: null, bomBusy: false,
    // Restore the page from the URL hash so a reload stays put (see parseHash).
    ...parseHash(),
  })
  const set = (patch: Partial<State>) => setS((prev) => ({ ...prev, ...patch }))

  // ---- Auth session ----
  // `user` is the signed-in account; `authReady` flips true once we've decided
  // whether an existing token still resolves to a valid session.
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authReady, setAuthReady] = useState(false)

  // On load, restore the session from a stored token (if any). A 401 clears it.
  useEffect(() => {
    if (!getToken()) { setAuthReady(true); return }
    let alive = true
    getMe()
      .then((u) => { if (alive) setUser(u) })
      .catch(() => { if (alive) setUser(null) })
      .finally(() => { if (alive) setAuthReady(true) })
    return () => { alive = false }
  }, [])

  // Keep React state in sync if the token is cleared elsewhere (e.g. a 401 mid-session).
  useEffect(() => onAuthChange(() => { if (!getToken()) setUser(null) }), [])

  const handleLogout = () => { apiLogout(); setUser(null) }

  useEffect(() => {
    const f = () => set({ vw: window.innerWidth })
    window.addEventListener('resize', f)
    return () => window.removeEventListener('resize', f)
  }, [])

  // Hydrate the backend bundle for one project; on failure the model falls back
  // to its literals. Pass an explicit id (e.g. right after creating a project) to
  // avoid the stale-closure value of s.projectId.
  const reload = (pid = s.projectId) =>
    loadModelData(pid || undefined).then((data) => set({ data })).catch(() => {})
  useEffect(() => { reload() }, [])

  // Refetch the workspace bundle whenever the open project changes, so each
  // project shows its own documents/quotes/etc. instead of the last one's.
  useEffect(() => { if (s.projectId) reload(s.projectId) }, [s.projectId])

  // Mirror the active page into the URL hash so a reload restores it. replaceState
  // (not pushState) keeps tab/page switches out of history so Back still leaves the
  // app rather than stepping through every internal navigation.
  useEffect(() => {
    const h = hashFor(s)
    if (typeof window !== 'undefined' && window.location.hash !== h) {
      window.history.replaceState(null, '', h)
    }
  }, [s.nav, s.projectId, s.tab, s.compare, s.comparePkg])

  // Honour manual hash edits and browser back/forward by re-syncing state.
  useEffect(() => {
    const onHash = () => set(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // Plan types the extractor supports (drives the upload selector).
  useEffect(() => {
    getPlanTypes().then((planTypes) => set({ planTypes })).catch(() => {})
  }, [])

  // Upload a plan into a slot (or an additional document), then refresh so it
  // appears in the documents list. `planType` selects the slot; uploading a
  // site/building/electrical plan replaces whatever occupied that slot before.
  const uploadDoc = async (file: File, planType?: string) => {
    set({ uploading: true, uploadError: null })
    try {
      await uploadDocument(file, planType || s.planType, s.projectId)
      set({ docIdx: 0 }) // newest doc lands at the top
      await reload()
    } catch (e) {
      set({ uploadError: 'Upload failed. Is the backend running?' })
    } finally {
      set({ uploading: false })
    }
  }

  // Remove a document (clear a slot, or drop an additional reference doc).
  const deleteDoc = async (id: string) => {
    try {
      await deleteDocument(id)
      set({ docIdx: 0, docLineItems: null })
      await reload()
    } catch (e) {
      set({ uploadError: 'Could not delete the document.' })
    }
  }

  // Create a hand-built custom BOM (no file). We name it, create the document,
  // then select it and drop straight into the BOM editor so the user can start
  // adding line items. It sorts newest-first, so it lands at docIdx 0.
  const activePid = () => s.projectId || (s.data && s.data.projects[0] && s.data.projects[0].id) || ''
  const createBom = async () => {
    const pid = activePid()
    if (!pid) { set({ uploadError: 'Open a project before creating a BOM.' }); return }
    const name = window.prompt('Name this bill of materials', 'Custom BOM')
    if (name === null) return
    try {
      const doc = await createManualBom(pid, name.trim() || 'Custom BOM')
      await reload()
      const groups = await getDocumentLineItems(doc.id)
      set({
        tab: 'documents', docIdx: 0, uploadError: null,
        docLineItems: { id: doc.id, groups },
        editBom: true,
        bomDraft: groups.map((g) => ({ ...g, items: g.items.map((it) => ({ ...it })) })),
      })
    } catch (e) {
      set({ uploadError: 'Could not create the BOM.' })
    }
  }

  // Poll while any document is still being analyzed.
  useEffect(() => {
    const docs = s.data && s.data.docs
    if (!docs || !docs.some((d) => d.processing || d.status === 'Processing')) return
    const t = setInterval(reload, 3000)
    return () => clearInterval(t)
  }, [s.data])

  // Load the selected document's extracted BOM groups.
  useEffect(() => {
    const docs = s.data && s.data.docs
    const doc = docs && docs[s.docIdx]
    if (!doc || !doc.id) { set({ docLineItems: null }); return }
    let alive = true
    getDocumentLineItems(doc.id)
      .then((groups) => { if (alive) set({ docLineItems: { id: doc.id, groups } }) })
      .catch(() => { if (alive) set({ docLineItems: null }) })
    return () => { alive = false }
  }, [s.docIdx, s.data])

  // ---- Human-in-the-loop BOM review ----
  const currentDoc = () => {
    const docs = s.data && s.data.docs
    return docs && docs[s.docIdx]
  }
  const startBomEdit = () => {
    const groups = (s.docLineItems && s.docLineItems.groups) || []
    set({ editBom: true, bomDraft: groups.map((g) => ({ ...g, items: g.items.map((it) => ({ ...it })) })) })
  }
  const cancelBomEdit = () => set({ editBom: false, bomDraft: null })
  const editBomItem = (gi: number, ii: number, field: string, value: string) =>
    set({ bomDraft: (s.bomDraft ?? []).map((g, i) => (i !== gi ? g : { ...g, items: g.items.map((it, j) => (j !== ii ? it : { ...it, [field]: value })) })) })
  const addBomItem = (gi: number) =>
    set({ bomDraft: (s.bomDraft ?? []).map((g, i) => (i !== gi ? g : { ...g, items: [...g.items, { n: '', q: '' }] })) })
  const deleteBomItem = (gi: number, ii: number) =>
    set({ bomDraft: (s.bomDraft ?? []).map((g, i) => (i !== gi ? g : { ...g, items: g.items.filter((_, j) => j !== ii) })) })
  const saveBom = async () => {
    const doc = currentDoc()
    if (!doc) return
    set({ bomBusy: true })
    try {
      await saveDocumentLineItems(doc.id, s.bomDraft ?? [])
      const groups = await getDocumentLineItems(doc.id)
      set({ editBom: false, bomDraft: null, docLineItems: { id: doc.id, groups } })
      await reload()
    } catch (e) {
      set({ uploadError: 'Could not save BOM edits.' })
    } finally {
      set({ bomBusy: false })
    }
  }
  const confirmBom = async () => {
    const doc = currentDoc()
    if (!doc) return
    set({ bomBusy: true })
    try { await confirmDocument(doc.id); await reload() } finally { set({ bomBusy: false }) }
  }

  const m = buildModel(s, set, {
    accent: 'blue', data: s.data, reload,
    user, onLogout: handleLogout, onUserUpdated: setUser,
    planTypes: s.planTypes, planType: s.planType,
    uploading: s.uploading, uploadError: s.uploadError,
    docLineItems: s.docLineItems, onUpload: uploadDoc, onDeleteDoc: deleteDoc, onCreateBom: createBom,
    editBom: s.editBom, bomDraft: s.bomDraft, bomBusy: s.bomBusy,
    startBomEdit, cancelBomEdit, editBomItem, addBomItem, deleteBomItem, saveBom, confirmBom,
  })

  // Until the stored token is validated, render nothing (avoids a login flash).
  if (!authReady) {
    return <div data-theme={s.theme} style={{ minHeight: '100vh', background: 'var(--bg)' }} />
  }
  // Gate the whole app behind authentication.
  if (!user) {
    return <Login theme={s.theme} onAuthed={(u) => setUser(u)} />
  }

  return (
    <div
      data-theme={m.theme} data-accent={m.accent}
      style={{ minHeight: '100vh', background: 'var(--bg)', color: 'var(--text)', display: 'flex' }}
    >
      {m.desktop && <Sidebar m={m} />}

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <Header m={m} />
        <main style={{ ...css('flex:1;padding:clamp(18px,2.4vw,30px);width:100%;max-width:1320px;margin:0 auto') }}>
          {m.isDashboard && <Dashboard m={m} />}
          {m.isProjects && <Projects m={m} />}
          {m.isSuppliers && <Suppliers m={m} />}
          {m.isSettings && <Settings m={m} />}
          {m.isDS && <DesignSystem m={m} />}
          {m.isProject && <ProjectWorkspace m={m} />}
        </main>
      </div>

      {m.supplierOpen && m.activeSupplier && <SupplierDrawer m={m} />}
      {m.mnavOpen && <MobileNav m={m} />}
      {m.newProjOpen && <NewProjectModal m={m} />}
    </div>
  )
}

/* ------------------------------------------------------------------ Sidebar */
function Sidebar({ m }: MProps) {
  return (
    <aside style={css('position:sticky;top:0;align-self:flex-start;height:100vh;width:248px;flex:none;border-right:1px solid var(--border);background:var(--panel);display:flex;flex-direction:column;padding:16px 12px;z-index:20')}>
      <div style={css('display:flex;align-items:center;gap:10px;padding:6px 8px 16px')}>
        <div style={css('width:30px;height:30px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:var(--shadow-sm)')}>
          <Svg size={17} sw={2.2} d='M3 7l9-4 9 4-9 4-9-4z" /><path d="M3 12l9 4 9-4" /><path d="M3 17l9 4 9-4' />
        </div>
        <div style={css('display:flex;flex-direction:column;line-height:1.1')}>
          <span style={css('font-size:15px;font-weight:700;letter-spacing:-.01em')}>ProcureAI</span>
          <span style={css('font-size:10px;font-weight:600;color:var(--text-3);letter-spacing:.04em')}>PROCUREMENT OS</span>
        </div>
      </div>
      <nav style={css('display:flex;flex-direction:column;gap:2px')}>
        <Box as="button" onClick={m.goDashboard} style={m.navStyle.dashboard} hover="background:var(--panel-2)">
          <Svg sw={1.9} d='<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>' />
          <span style={css('flex:1;text-align:left')}>Dashboard</span>
        </Box>
        <Box as="button" onClick={m.goProjects} style={m.navStyle.projects} hover="background:var(--panel-2)">
          <Svg sw={1.9} d='M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z' />
          <span style={css('flex:1;text-align:left')}>Projects</span>
          <span style={css('font-size:11px;font-weight:600;color:var(--text-3);background:var(--panel-3);padding:1px 7px;border-radius:999px')}>{m.projectCount}</span>
        </Box>
        <Box as="button" onClick={m.goSuppliers} style={m.navStyle.suppliers} hover="background:var(--panel-2)">
          <Svg sw={1.9} d='<rect x="5" y="3" width="14" height="18" rx="1.6"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M10 21v-3h4v3"/>' />
          <span style={css('flex:1;text-align:left')}>Suppliers</span>
        </Box>
        <Box as="button" onClick={m.goSettings} style={m.navStyle.settings} hover="background:var(--panel-2)">
          <Svg sw={1.9} d='<circle cx="12" cy="12" r="3"/><path d="M19.4 13a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-2.87 1.2v.17a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-2.87-1.2l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 11h-.17a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 6.5 4.13l-.06-.06A2 2 0 1 1 9.27 1.24l.06.06a1.7 1.7 0 0 0 2.87-1.2"/>' />
          <span style={css('flex:1;text-align:left')}>Settings</span>
        </Box>
      </nav>
      <div style={{ flex: 1 }}></div>
      <Box as="button" onClick={m.goDS} style={m.navStyle.ds} hover="background:var(--panel-2)">
        <Svg sw={1.9} d='<circle cx="13.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="13" r="2.5"/><circle cx="8.5" cy="7.5" r="2.5"/><circle cx="6.5" cy="14.5" r="2.5"/><path d="M12 22a5 5 0 0 1-3-9"/>' />
        <span style={css('flex:1;text-align:left')}>Design System</span>
      </Box>
      <div style={css('display:flex;align-items:center;gap:10px;margin-top:8px;padding:9px 8px;border-top:1px solid var(--border)')}>
        <div style={css('width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#7c3aed);color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex:none')}>{m.userInitials}</div>
        <div style={css('display:flex;flex-direction:column;line-height:1.2;min-width:0;flex:1')}>
          <span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{m.userName}</span>
          <span style={css('font-size:11px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{m.userCompany || m.userEmail}</span>
        </div>
        <Box as="button" onClick={m.logout} title="Sign out" style={css('width:28px;height:28px;border-radius:7px;display:flex;align-items:center;justify-content:center;color:var(--text-3);flex:none')} hover="background:var(--panel-2);color:var(--text)">
          <Svg size={16} d='M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9' />
        </Box>
      </div>
    </aside>
  )
}

/* ------------------------------------------------------------------- Header */
function Header({ m }: MProps) {
  return (
    <header style={css('position:sticky;top:0;z-index:30;min-height:57px;display:flex;align-items:center;gap:12px;padding:0 clamp(14px,2vw,26px);border-bottom:1px solid var(--border);background:var(--panel)')}>
      {m.mobile && (
        <Box as="button" onClick={m.toggleMnav} style={css('width:34px;height:34px;border-radius:8px;display:flex;align-items:center;justify-content:center;border:1px solid var(--border)')} hover="background:var(--panel-2)">
          <Svg size={18} d='M4 6h16M4 12h16M4 18h16' />
        </Box>
      )}
      <div style={css('display:flex;align-items:center;gap:8px;min-width:0')}>
        <span style={css('font-size:14px;font-weight:500;color:var(--text-2);white-space:nowrap')}>{m.crumbMain}</span>
        {m.hasSub && (
          <>
            <Svg size={15} stroke="var(--text-3)" d={CHEVRON} style={{ flex: 'none' }} />
            <span style={css('font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{m.crumbSub}</span>
          </>
        )}
      </div>
      <div style={{ flex: 1 }}></div>
      {m.desktop && (
        <div style={css('display:flex;align-items:center;gap:8px;height:34px;padding:0 12px;border-radius:8px;background:var(--panel-2);border:1px solid var(--border);color:var(--text-3);min-width:200px')}>
          <Svg size={15} d='<circle cx="11" cy="11" r="7"/><path d="m20 20-3-3"/>' />
          <span style={css('font-size:13px')}>Search projects, suppliers…</span>
          <span style={{ flex: 1 }}></span>
          <span style={css('font-size:11px;border:1px solid var(--border-strong);border-radius:5px;padding:1px 5px')}>⌘K</span>
        </div>
      )}
      <Box as="button" onClick={m.toggleTheme} title="Toggle theme" style={css('width:34px;height:34px;border-radius:8px;display:flex;align-items:center;justify-content:center;border:1px solid var(--border);color:var(--text-2)')} hover="background:var(--panel-2)">
        {m.isDark
          ? <Svg d='<circle cx="12" cy="12" r="4.5"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/>' />
          : <Svg d='M21 12.5A8.5 8.5 0 1 1 11.5 3a6.5 6.5 0 0 0 9.5 9.5z' />}
      </Box>
    </header>
  )
}

/* ---------------------------------------------------------------- Dashboard */
function Dashboard({ m }: MProps) {
  return (
    <div style={css('animation:pcUp .25s ease both')}>
      <div style={css('display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px')}>
        <div>
          <h1 style={css('margin:0;font-size:clamp(22px,3vw,27px);font-weight:700;letter-spacing:-.02em')}>{m.greeting}, {m.firstName}</h1>
          <p style={css('margin:5px 0 0;font-size:14px;color:var(--text-2)')}>{m.projectCount > 0 ? `Portfolio snapshot across ${m.projectCount} active project${m.projectCount === 1 ? '' : 's'}` : 'No projects yet — create one to get started'}</p>
        </div>
        <Box as="button" onClick={m.openNewProject} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13.5px;font-weight:600;box-shadow:var(--shadow-sm)')} hover="background:var(--primary-2)">
          <Svg size={16} sw={2.2} d={PLUS} />New project
        </Box>
      </div>

      {m.metrics.length > 0 && (
      <div style={css('display:grid;grid-template-columns:repeat(auto-fit,minmax(186px,1fr));gap:13px;margin-bottom:26px')}>
        {m.metrics.map((mm, i) => (
          <div key={i} style={css('background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:15px 17px;box-shadow:var(--shadow-sm);display:flex;flex-direction:column;gap:11px')}>
            <div style={css('display:flex;align-items:center;justify-content:space-between;gap:8px')}>
              <span style={css('font-size:12.5px;font-weight:600;color:var(--text-2)')}>{mm.label}</span>
              {mm.ai && <span style={css('display:inline-flex;align-items:center;gap:3px;font-size:10px;font-weight:700;color:var(--primary);background:var(--primary-soft);padding:2px 6px;border-radius:5px')}><Svg size={10} fill d='M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8z' />AI</span>}
              {mm.risk && <span style={css('width:8px;height:8px;border-radius:50%;background:var(--danger)')}></span>}
            </div>
            <div style={css("font-family:'JetBrains Mono',monospace;font-size:25px;font-weight:600;letter-spacing:-.02em")}>{mm.value}</div>
            <div style={css('display:flex;align-items:center;gap:5px;font-size:12px;font-weight:600')}>
              <span style={mm.deltaStyle}>
                {mm.up && <Svg size={12} sw={2.4} d='M12 19V5M6 11l6-6 6 6' />}
                {mm.down && <Svg size={12} sw={2.4} d='M12 5v14M6 13l6 6 6-6' />}
                {mm.delta}
              </span>
              <span style={css('color:var(--text-3);font-weight:500')}>{mm.sub}</span>
            </div>
          </div>
        ))}
      </div>
      )}

      <div style={css('display:grid;grid-template-columns:minmax(0,1.9fr) minmax(0,1fr);gap:18px;align-items:start')}>
        <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
          <div style={css('display:flex;align-items:center;justify-content:space-between;padding:15px 18px;border-bottom:1px solid var(--border)')}>
            <h2 style={css('margin:0;font-size:15px;font-weight:600')}>Project overview</h2>
            <Box as="button" onClick={m.goProjects} style={css('font-size:12.5px;font-weight:600;color:var(--primary)')} hover="color:var(--primary-2)">View all →</Box>
          </div>
          <div style={css('overflow-x:auto')}>
            <div style={css('min-width:640px')}>
              <div style={css('display:grid;grid-template-columns:minmax(180px,1.7fr) minmax(120px,1.3fr) 70px 78px 96px;gap:10px;padding:9px 18px;border-bottom:1px solid var(--border);font-size:11px;font-weight:700;letter-spacing:.04em;color:var(--text-3);text-transform:uppercase')}>
                <span>Project</span><span>Procurement</span><span style={css('text-align:center')}>RFQs</span><span style={css('text-align:center')}>Quotes</span><span style={css('text-align:right')}>Risk</span>
              </div>
              {m.projects.map((p, i) => (
                <Box as="button" key={i} onClick={() => m.openProject(p)} style={css('display:grid;grid-template-columns:minmax(180px,1.7fr) minmax(120px,1.3fr) 70px 78px 96px;gap:10px;width:100%;padding:13px 18px;border-bottom:1px solid var(--border);align-items:center;text-align:left')} hover="background:var(--panel-2)">
                  <div style={css('min-width:0')}>
                    <div style={css('font-size:13.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{p.name}</div>
                    <div style={css('font-size:11.5px;color:var(--text-3)')}>{p.loc}</div>
                  </div>
                  <div style={css('display:flex;align-items:center;gap:8px')}>
                    <div style={css('flex:1;height:6px;border-radius:999px;background:var(--panel-3);overflow:hidden')}><div style={p.barStyle}></div></div>
                    <span style={css("font-size:11.5px;font-weight:600;color:var(--text-2);font-family:'JetBrains Mono',monospace;width:30px;text-align:right")}>{p.progress}%</span>
                  </div>
                  <span style={css("text-align:center;font-size:13px;font-weight:600;font-family:'JetBrains Mono',monospace")}>{p.rfqs}</span>
                  <span style={css("text-align:center;font-size:13px;font-weight:600;font-family:'JetBrains Mono',monospace")}>{p.quotes}</span>
                  <span style={css('display:flex;justify-content:flex-end')}><span style={p.riskBadge}>{p.risk}</span></span>
                </Box>
              ))}
              {m.projects.length === 0 && (
                <div style={css('padding:36px 18px;text-align:center;font-size:13px;color:var(--text-3)')}>No projects yet — create one to get started.</div>
              )}
            </div>
          </div>
        </div>

        <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
          <div style={css('display:flex;align-items:center;justify-content:space-between;padding:15px 18px;border-bottom:1px solid var(--border)')}>
            <h2 style={css('margin:0;font-size:15px;font-weight:600')}>Recent activity</h2>
            <span style={css('width:7px;height:7px;border-radius:50%;background:var(--success);box-shadow:0 0 0 3px var(--success-soft)')}></span>
          </div>
          <div style={css('padding:6px 8px')}>
            {m.activity.map((a, i) => (
              <Box key={i} style={css('display:flex;gap:11px;padding:10px;border-radius:10px')} hover="background:var(--panel-2)">
                <div style={a.chipStyle}><IconHtml html={a.iconHtml} /></div>
                <div style={css('flex:1;min-width:0')}>
                  <div style={css('font-size:13px;font-weight:500;line-height:1.35')}>{a.title}</div>
                  <div style={css('font-size:11.5px;color:var(--text-3);margin-top:1px')}>{a.meta}</div>
                </div>
                <span style={css('font-size:11px;color:var(--text-3);white-space:nowrap')}>{a.time}</span>
              </Box>
            ))}
            {m.activity.length === 0 && (
              <div style={css('padding:28px 12px;text-align:center;font-size:12.5px;color:var(--text-3)')}>No activity yet.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ----------------------------------------------------------------- Projects */
function Projects({ m }: MProps) {
  return (
    <div style={css('animation:pcUp .25s ease both')}>
      <div style={css('display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:20px')}>
        <div>
          <h1 style={css('margin:0;font-size:clamp(22px,3vw,27px);font-weight:700;letter-spacing:-.02em')}>Projects</h1>
          <p style={css('margin:5px 0 0;font-size:14px;color:var(--text-2)')}>{m.projectCount} active · everything in ProcureAI lives inside a project</p>
        </div>
        <Box as="button" onClick={m.openNewProject} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13.5px;font-weight:600;box-shadow:var(--shadow-sm)')} hover="background:var(--primary-2)">
          <Svg size={16} sw={2.2} d={PLUS} />New project
        </Box>
      </div>
      {m.projError && (
        <div style={css('display:flex;align-items:center;gap:11px;margin-bottom:16px;padding:12px 14px;border-radius:11px;background:var(--danger-soft,rgba(220,38,38,.1));border:1px solid var(--danger);color:var(--danger)')}>
          <Svg size={17} d='<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>' />
          <span style={css('flex:1;font-size:13px;font-weight:500')}>{m.projError}</span>
          <Box as="button" onClick={m.dismissProjError} title="Dismiss" style={css('width:26px;height:26px;border-radius:7px;display:flex;align-items:center;justify-content:center;color:var(--danger);flex:none')} hover="background:var(--danger-soft,rgba(220,38,38,.16))">
            <Svg size={15} d='M6 6l12 12M18 6 6 18' />
          </Box>
        </div>
      )}
      {m.projects.length === 0 ? (
        <div style={css('background:var(--panel);border:1px dashed var(--border-strong);border-radius:16px;padding:48px 24px;text-align:center')}>
          <div style={css('font-size:15px;font-weight:600;margin-bottom:6px')}>No projects yet</div>
          <div style={css('font-size:13px;color:var(--text-3)')}>Create a project to start uploading plans and sourcing materials.</div>
        </div>
      ) : (
      <div style={css('display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:15px')}>
        {m.projects.map((p, i) => (
          <Box as="button" key={i} onClick={() => m.openProject(p)} style={css('text-align:left;background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:18px;box-shadow:var(--shadow-sm);display:flex;flex-direction:column;gap:14px;transition:box-shadow .15s,transform .15s,border-color .15s')} hover="box-shadow:var(--shadow-md);transform:translateY(-2px);border-color:var(--border-strong)">
            <div style={css('display:flex;align-items:flex-start;justify-content:space-between;gap:10px')}>
              <div style={css('min-width:0')}>
                <div style={css('font-size:15.5px;font-weight:600;letter-spacing:-.01em;line-height:1.25')}>{p.name}</div>
                <div style={css('display:flex;align-items:center;gap:5px;font-size:12.5px;color:var(--text-3);margin-top:3px')}><Svg size={13} d={PIN} />{p.loc}</div>
              </div>
              <Box
                onClick={(e: MouseEvent) => {
                  e.stopPropagation()
                  if (window.confirm(`Delete “${p.name}”? This permanently removes its documents, quotes and RFQs.`)) m.deleteProject(p.id)
                }}
                title="Delete project"
                style={css('width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--text-3);flex:none')}
                hover="background:var(--danger-soft,rgba(220,38,38,.12));color:var(--danger)"
              >
                <Svg size={15} sw={1.9} d={TRASH} />
              </Box>
            </div>
            <div>
              <div style={css('display:flex;align-items:center;justify-content:space-between;font-size:12px;margin-bottom:6px')}><span style={css('color:var(--text-2);font-weight:500')}>Procurement progress</span><span style={css("font-weight:600;font-family:'JetBrains Mono',monospace")}>{p.progress}%</span></div>
              <div style={css('height:7px;border-radius:999px;background:var(--panel-3);overflow:hidden')}><div style={p.barStyle}></div></div>
            </div>
            <div style={css('display:flex;gap:8px;padding-top:13px;border-top:1px solid var(--border)')}>
              <div style={{ flex: 1 }}><div style={css('font-size:11px;color:var(--text-3)')}>Value</div><div style={css("font-size:14px;font-weight:600;font-family:'JetBrains Mono',monospace")}>{p.value}</div></div>
              <div style={{ flex: 1 }}><div style={css('font-size:11px;color:var(--text-3)')}>Suppliers</div><div style={css("font-size:14px;font-weight:600;font-family:'JetBrains Mono',monospace")}>{p.suppliers}</div></div>
              <div style={{ flex: 1 }}><div style={css('font-size:11px;color:var(--text-3)')}>Open RFQs</div><div style={css("font-size:14px;font-weight:600;font-family:'JetBrains Mono',monospace")}>{p.rfqs}</div></div>
            </div>
          </Box>
        ))}
      </div>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- Suppliers */
function SupplierCard({ x }: { x: Model['suppliers'][number] }) {
  return (
    <Box as="button" onClick={x.onOpen} style={css('text-align:left;background:var(--panel);border:1px solid var(--border);border-radius:15px;padding:16px;box-shadow:var(--shadow-sm);display:flex;flex-direction:column;gap:13px;transition:box-shadow .15s,transform .15s')} hover="box-shadow:var(--shadow-md);transform:translateY(-2px)">
      <div style={css('display:flex;align-items:flex-start;gap:11px')}>
        <div style={x.logoStyle}>{x.logo}</div>
        <div style={css('flex:1;min-width:0')}><div style={css('font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{x.name}</div><div style={css('font-size:12px;color:var(--text-3)')}>{x.contact}</div></div>
        <span style={x.rfqBadge}>{x.rfq}</span>
      </div>
      <div style={css('display:flex;gap:6px;flex-wrap:wrap')}>
        {x.cats.map((cat, i) => <span key={i} style={css('font-size:11px;font-weight:500;color:var(--text-2);background:var(--panel-3);padding:2px 9px;border-radius:6px')}>{cat}</span>)}
      </div>
      <div style={css('display:flex;gap:8px;padding-top:12px;border-top:1px solid var(--border)')}>
        <div style={{ flex: 1 }}><div style={css('font-size:11px;color:var(--text-3)')}>Quotes</div><div style={css("font-size:13.5px;font-weight:600;font-family:'JetBrains Mono',monospace")}>{x.quotes}</div></div>
        <div style={{ flex: 1.2 }}><div style={css('font-size:11px;color:var(--text-3)')}>Total value</div><div style={css("font-size:13.5px;font-weight:600;font-family:'JetBrains Mono',monospace")}>{x.quoteVal}</div></div>
        <div style={{ flex: 1.3 }}><div style={css('font-size:11px;color:var(--text-3)')}>Last contact</div><div style={css('font-size:12.5px;font-weight:500')}>{x.last}</div></div>
      </div>
    </Box>
  )
}
function Suppliers({ m }: MProps) {
  const [adding, setAdding] = useState(false)
  return (
    <div style={css('animation:pcUp .25s ease both')}>
      <div style={css('display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:20px')}>
        <div>
          <h1 style={css('margin:0;font-size:clamp(22px,3vw,27px);font-weight:700;letter-spacing:-.02em')}>Suppliers</h1>
          <p style={css('margin:5px 0 0;font-size:14px;color:var(--text-2)')}>Your network across all projects · {m.suppliers.length} shown</p>
        </div>
        <Box as="button" onClick={() => setAdding(true)} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13.5px;font-weight:600;box-shadow:var(--shadow-sm)')} hover="background:var(--primary-2)">
          <Svg size={16} sw={2.2} d={PLUS} />Add supplier
        </Box>
      </div>
      {m.suppliers.length === 0 ? (
        <div style={css('background:var(--panel);border:1px dashed var(--border-strong);border-radius:16px;padding:48px 24px;text-align:center')}>
          <div style={css('font-size:15px;font-weight:600;margin-bottom:6px')}>No suppliers yet</div>
          <div style={css('font-size:13px;color:var(--text-3)')}>Add one with “Add supplier”, or search and add them from a project.</div>
        </div>
      ) : (
      <div style={css('display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px')}>
        {m.suppliers.map((x, i) => <SupplierCard key={i} x={x} />)}
      </div>
      )}
      {adding && <AddSupplierModal onClose={() => setAdding(false)} onSaved={async () => { await m.reload(); setAdding(false) }} />}
    </div>
  )
}

// Manual "add a supplier to my network" form (the Suppliers page). Only a name
// is required; the backend dedups by name so re-adding is a no-op.
function AddSupplierModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void | Promise<void> }) {
  const [name, setName] = useState('')
  const [contact, setContact] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [web, setWeb] = useState('')
  const [cats, setCats] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setErr('A supplier name is required.'); return }
    setSaving(true); setErr(null)
    try {
      await createSupplier({
        name: name.trim(), contact, phone, email, web,
        cats: cats.split(',').map((c) => c.trim()).filter(Boolean),
      })
      await onSaved()
    } catch { setErr('Could not add supplier — is the backend running?'); setSaving(false) }
  }

  const field = css("width:100%;height:36px;padding:0 11px;border-radius:9px;border:1px solid var(--border);background:var(--panel-2);color:var(--text);font-size:13px;box-sizing:border-box")
  const label = css('font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--text-3);margin-bottom:5px')
  return (
    <div onClick={onClose} style={css('position:fixed;inset:0;background:rgba(15,23,42,.45);display:flex;align-items:center;justify-content:center;padding:20px;z-index:50')}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={submit} style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-md);width:460px;max-width:100%;max-height:90vh;overflow:auto;padding:22px')}>
        <div style={css('display:flex;align-items:center;gap:9px;margin-bottom:16px')}>
          <span style={css('width:26px;height:26px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={15} sw={2.2} d={PLUS} /></span>
          <h2 style={css('margin:0;font-size:15px;font-weight:600;flex:1')}>Add supplier to your network</h2>
        </div>
        <div style={css('display:flex;flex-direction:column;gap:13px')}>
          <div><div style={label}>Name *</div><input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ferguson Waterworks" style={field} /></div>
          <div style={css('display:flex;gap:11px')}>
            <div style={css('flex:1')}><div style={label}>Contact</div><input value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Contact name" style={field} /></div>
            <div style={css('flex:1')}><div style={label}>Phone</div><input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(555) 555-0100" style={field} /></div>
          </div>
          <div><div style={label}>Email</div><input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="sales@example.com" style={field} /></div>
          <div><div style={label}>Website</div><input value={web} onChange={(e) => setWeb(e.target.value)} placeholder="example.com" style={field} /></div>
          <div><div style={label}>Categories</div><input value={cats} onChange={(e) => setCats(e.target.value)} placeholder="Water, Sewer (comma-separated)" style={field} /></div>
        </div>
        {err && <div style={css('font-size:12.5px;color:var(--danger);margin-top:12px')}>{err}</div>}
        <div style={css('display:flex;justify-content:flex-end;gap:9px;margin-top:20px')}>
          <Box as="button" type="button" onClick={onClose} style={css('height:36px;padding:0 15px;border-radius:9px;background:var(--panel);border:1px solid var(--border);color:var(--text);font-size:13px;font-weight:600')} hover="background:var(--panel-2)">Cancel</Box>
          <Box as="button" type="submit" disabled={saving} style={css(`display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 16px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13px;font-weight:600;opacity:${saving ? '.6' : '1'}`)} hover="background:var(--primary-2)">
            {saving ? 'Adding…' : 'Add supplier'}
          </Box>
        </div>
      </form>
    </div>
  )
}

/* ----------------------------------------------------------------- Settings */
function Settings({ m }: MProps) {
  const toggleOn = css('width:38px;height:22px;border-radius:999px;background:var(--primary);position:relative;flex:none')
  // RFQ sender address — the one writable setting; saves via PATCH /api/auth/me.
  const [senderEmail, setSenderEmail] = useState(m.userSenderEmail)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // Email-config verification (POST /api/auth/test-email).
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)
  const [testErr, setTestErr] = useState<string | null>(null)
  const runTestEmail = async () => {
    setTesting(true); setTestResult(null); setTestErr(null)
    try {
      const r = await sendTestEmail()
      setTestResult(
        r.mocked
          ? 'Mock mode — no Gmail connected, the send was only logged. See docs/email-setup.md.'
          : `Sent to ${r.to} from ${r.fromAddr} — check your inbox (and the From address).`,
      )
    } catch (ex) {
      setTestErr(ex instanceof Error ? ex.message : 'Test send failed')
    } finally {
      setTesting(false)
    }
  }
  const dirty = senderEmail.trim() !== m.userSenderEmail
  const saveSender = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true); setErr(null); setSaved(false)
    try {
      const u = await updateMe({ senderEmail: senderEmail.trim() || null })
      m.onUserUpdated(u)
      setSenderEmail((u.senderEmail as string) || '')
      setSaved(true)
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'Could not save')
    } finally {
      setSaving(false)
    }
  }
  return (
    <div style={css('animation:pcUp .25s ease both;max-width:680px')}>
      <h1 style={css('margin:0 0 4px;font-size:clamp(22px,3vw,27px);font-weight:700;letter-spacing:-.02em')}>Settings</h1>
      <p style={css('margin:0 0 22px;font-size:14px;color:var(--text-2)')}>Manage your workspace and procurement defaults</p>
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
        <div style={css('display:flex;align-items:center;gap:14px;padding:18px;border-bottom:1px solid var(--border)')}>
          <div style={css('width:46px;height:46px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#7c3aed);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600')}>{m.userInitials}</div>
          <div style={{ flex: 1 }}><div style={css('font-size:15px;font-weight:600')}>{m.userName}</div><div style={css('font-size:12.5px;color:var(--text-3)')}>{m.userEmail}{m.userCompany ? ` · ${m.userCompany}` : ''}</div></div>
          <Box as="button" onClick={m.logout} style={css('height:34px;padding:0 13px;border-radius:8px;border:1px solid var(--border);font-size:12.5px;font-weight:600')} hover="background:var(--panel-2)">Sign out</Box>
        </div>
        <div style={css('padding:8px 0')}>
          <div style={css('display:flex;align-items:center;justify-content:space-between;padding:14px 18px')}>
            <div><div style={css('font-size:13.5px;font-weight:600')}>Appearance</div><div style={css('font-size:12px;color:var(--text-3)')}>Theme used across the workspace</div></div>
            <Box as="button" onClick={m.toggleTheme} style={css('height:32px;padding:0 13px;border-radius:8px;border:1px solid var(--border);font-size:12.5px;font-weight:600;display:flex;align-items:center;gap:6px')} hover="background:var(--panel-2)">{m.isDark ? 'Dark' : 'Light'}</Box>
          </div>
          <form onSubmit={saveSender} style={css('display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 18px;border-top:1px solid var(--border)')}>
            <div style={{ flex: 1 }}>
              <div style={css('font-size:13.5px;font-weight:600')}>RFQ sender address</div>
              <div style={css('font-size:12px;color:var(--text-3)')}>Outgoing RFQs are sent from this address. Must be a verified send-as alias on the connected Gmail account, or Gmail rewrites it.</div>
              {err && <div style={css('font-size:12px;color:var(--danger);margin-top:4px')}>{err}</div>}
            </div>
            <div style={css('display:flex;align-items:center;gap:8px;flex:none')}>
              <input
                type="email"
                value={senderEmail}
                onChange={(e) => { setSenderEmail(e.target.value); setSaved(false); setErr(null) }}
                placeholder="Workspace default"
                style={css('height:32px;width:210px;padding:0 10px;border-radius:8px;border:1px solid var(--border);background:var(--panel-2);color:var(--text);font-size:12.5px;outline:none')}
              />
              <Box as="button" type="submit" disabled={saving || !dirty} style={css(`height:32px;padding:0 13px;border-radius:8px;border:1px solid var(--border);font-size:12.5px;font-weight:600;${saving || !dirty ? 'opacity:.55' : ''}`)} hover="background:var(--panel-2)">
                {saving ? 'Saving…' : saved && !dirty ? 'Saved ✓' : 'Save'}
              </Box>
            </div>
          </form>
          <div style={css('display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 18px;border-top:1px solid var(--border)')}>
            <div style={{ flex: 1 }}>
              <div style={css('font-size:13.5px;font-weight:600')}>Email delivery</div>
              <div style={css('font-size:12px;color:var(--text-3)')}>Send yourself a test email through the same path RFQs use. Setup guide: docs/email-setup.md</div>
              {testResult && <div style={css('font-size:12px;color:var(--success,#16a34a);margin-top:4px')}>{testResult}</div>}
              {testErr && <div style={css('font-size:12px;color:var(--danger);margin-top:4px')}>{testErr}</div>}
            </div>
            <Box as="button" onClick={runTestEmail} disabled={testing} style={css(`height:32px;padding:0 13px;border-radius:8px;border:1px solid var(--border);font-size:12.5px;font-weight:600;flex:none;${testing ? 'opacity:.55' : ''}`)} hover="background:var(--panel-2)">
              {testing ? 'Sending…' : 'Send test email'}
            </Box>
          </div>
          <div style={css('display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-top:1px solid var(--border)')}>
            <div><div style={css('font-size:13.5px;font-weight:600')}>Default RFQ due window</div><div style={css('font-size:12px;color:var(--text-3)')}>Days suppliers get to respond</div></div>
            <span style={css("font-size:13px;font-weight:600;font-family:'JetBrains Mono',monospace;background:var(--panel-2);padding:5px 11px;border-radius:8px;border:1px solid var(--border)")}>7 days</span>
          </div>
          <div style={css('display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-top:1px solid var(--border)')}>
            <div><div style={css('font-size:13.5px;font-weight:600')}>AI auto-follow-up</div><div style={css('font-size:12px;color:var(--text-3)')}>Nudge non-responsive suppliers automatically</div></div>
            <span style={toggleOn}><span style={css('position:absolute;top:2px;right:2px;width:18px;height:18px;border-radius:50%;background:#fff')}></span></span>
          </div>
          <div style={css('display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-top:1px solid var(--border)')}>
            <div><div style={css('font-size:13.5px;font-weight:600')}>Email notifications</div><div style={css('font-size:12px;color:var(--text-3)')}>Quote received & risk alerts</div></div>
            <span style={toggleOn}><span style={css('position:absolute;top:2px;right:2px;width:18px;height:18px;border-radius:50%;background:#fff')}></span></span>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- DesignSystem */
function DesignSystem({ m }: MProps) {
  const swatch = (bg: string, label: string, extra?: CSSProperties) => (
    <div><div style={{ height: 46, borderRadius: 9, background: bg, ...(extra || {}) }}></div><div style={css('font-size:10.5px;color:var(--text-3);margin-top:5px')}>{label}</div></div>
  )
  return (
    <div style={css('animation:pcUp .25s ease both')}>
      <h1 style={css('margin:0 0 4px;font-size:clamp(22px,3vw,27px);font-weight:700;letter-spacing:-.02em')}>Design System</h1>
      <p style={css('margin:0 0 24px;font-size:14px;color:var(--text-2)')}>The primitives behind ProcureAI — Figtree + JetBrains Mono, an enterprise-blue palette, and AI-native components</p>
      <div style={css('display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px')}>
        <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:18px')}>
          <div style={css('font-size:13px;font-weight:700;margin-bottom:14px')}>Color</div>
          <div style={css('display:grid;grid-template-columns:repeat(4,1fr);gap:9px')}>
            {swatch('var(--primary)', 'Primary')}{swatch('var(--success)', 'Success')}{swatch('var(--warn)', 'Warning')}{swatch('var(--danger)', 'Danger')}
            {swatch('var(--violet)', 'Accent')}{swatch('var(--text)', 'Ink')}{swatch('var(--panel-3)', 'Subtle')}{swatch('var(--bg)', 'Canvas', { border: '1px solid var(--border)' })}
          </div>
        </div>
        <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:18px')}>
          <div style={css('font-size:13px;font-weight:700;margin-bottom:14px')}>Typography</div>
          <div style={css('display:flex;flex-direction:column;gap:11px')}>
            <div style={css('display:flex;align-items:baseline;gap:12px')}><span style={css('font-size:26px;font-weight:700;letter-spacing:-.02em')}>Display</span><span style={css("font-size:11px;color:var(--text-3);font-family:'JetBrains Mono',monospace")}>Figtree 700 · 26</span></div>
            <div style={css('display:flex;align-items:baseline;gap:12px')}><span style={css('font-size:18px;font-weight:600')}>Heading</span><span style={css("font-size:11px;color:var(--text-3);font-family:'JetBrains Mono',monospace")}>600 · 18</span></div>
            <div style={css('display:flex;align-items:baseline;gap:12px')}><span style={css('font-size:13.5px')}>Body text</span><span style={css("font-size:11px;color:var(--text-3);font-family:'JetBrains Mono',monospace")}>400 · 13.5</span></div>
            <div style={css('display:flex;align-items:baseline;gap:12px')}><span style={css("font-size:15px;font-weight:600;font-family:'JetBrains Mono',monospace")}>$145,472</span><span style={css("font-size:11px;color:var(--text-3);font-family:'JetBrains Mono',monospace")}>Mono · data</span></div>
          </div>
        </div>
        <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:18px')}>
          <div style={css('font-size:13px;font-weight:700;margin-bottom:14px')}>Status badges</div>
          <div style={css('display:flex;flex-wrap:wrap;gap:8px')}>
            <span style={m.badgeBlue}>RFQs Out</span><span style={m.badgeSuccess}>Quoted</span><span style={m.badgeWarn}>Awaiting</span><span style={m.badgeDanger}>High Risk</span><span style={m.badgeViolet}>Quotes In</span><span style={m.badgeGray}>Draft</span>
          </div>
          <div style={css('font-size:13px;font-weight:700;margin:18px 0 12px')}>Progress</div>
          <div style={css('height:8px;border-radius:999px;background:var(--panel-3);overflow:hidden;margin-bottom:9px')}><div style={css('width:90%;height:100%;border-radius:999px;background:var(--success)')}></div></div>
          <div style={css('height:8px;border-radius:999px;background:var(--panel-3);overflow:hidden')}><div style={css('width:40%;height:100%;border-radius:999px;background:var(--primary)')}></div></div>
        </div>
        <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:18px')}>
          <div style={css('font-size:13px;font-weight:700;margin-bottom:14px')}>Buttons & inputs</div>
          <div style={css('display:flex;flex-wrap:wrap;gap:9px;align-items:center;margin-bottom:14px')}>
            <span style={css('display:inline-flex;align-items:center;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:#fff;font-size:13px;font-weight:600')}>Primary</span>
            <span style={css('display:inline-flex;align-items:center;height:36px;padding:0 14px;border-radius:9px;background:var(--panel);border:1px solid var(--border);font-size:13px;font-weight:600')}>Secondary</span>
            <span style={css('display:inline-flex;align-items:center;height:36px;padding:0 14px;border-radius:9px;color:var(--primary);font-size:13px;font-weight:600')}>Ghost</span>
          </div>
          <div style={css('display:flex;align-items:center;gap:8px;height:36px;padding:0 12px;border-radius:9px;background:var(--panel-2);border:1px solid var(--border);color:var(--text-3);font-size:13px')}><Svg size={15} d='<circle cx="11" cy="11" r="7"/><path d="m20 20-3-3"/>' />Input field</div>
        </div>
        <div style={css('grid-column:1/-1;background:var(--primary-softer);border:1px solid var(--primary-soft);border-radius:16px;box-shadow:var(--shadow-sm);padding:18px')}>
          <div style={css('font-size:13px;font-weight:700;margin-bottom:12px')}>AI insight component</div>
          <div style={css('display:flex;align-items:flex-start;gap:11px')}>
            <span style={css('width:28px;height:28px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={16} fill d='M12 2l1.7 4.6L18 8l-4.3 1.4L12 14l-1.7-4.6L6 8l4.3-1.4z' /></span>
            <div><div style={css('font-size:13px;font-weight:700;color:var(--primary);margin-bottom:3px')}>ProcureAI suggests</div><div style={css('font-size:13px;line-height:1.5;color:var(--text)')}>A consistent blue-tinted surface, the sparkle mark, and a primary label distinguish anything AI-generated from human-entered data across the product.</div></div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------- Project workspace shell */
function ProjectWorkspace({ m }: MProps) {
  return (
    <div style={css('animation:pcUp .25s ease both')}>
      <div style={css('display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:18px')}>
        <div style={css('min-width:0')}>
          <div style={css('display:flex;align-items:center;gap:11px;flex-wrap:wrap')}>
            <h1 style={css('margin:0;font-size:clamp(20px,2.6vw,25px);font-weight:700;letter-spacing:-.02em')}>{m.activeProject.name}</h1>
          </div>
          <div style={css('display:flex;align-items:center;gap:18px;margin-top:7px;font-size:13px;color:var(--text-2);flex-wrap:wrap')}>
            {m.activeProject.loc && <span style={css('display:flex;align-items:center;gap:5px')}><Svg size={14} d={PIN} />{m.activeProject.loc}</span>}
            {m.activeProject.value && <span>Value <strong style={css("color:var(--text);font-family:'JetBrains Mono',monospace")}>{m.activeProject.value}</strong></span>}
          </div>
        </div>
        <div style={css('display:flex;gap:9px;flex-wrap:wrap')}>
          <Box as="button" onClick={m.setDocuments} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 13px;border-radius:9px;background:var(--panel);border:1px solid var(--border);color:var(--text);font-size:13px;font-weight:600')} hover="background:var(--panel-2)"><Svg size={15} d='M12 16V4M7 9l5-5 5 5" /><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2' />Upload</Box>
          <Box as="button" onClick={m.setSuppliers} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 13px;border-radius:9px;background:var(--panel);border:1px solid var(--border);color:var(--text);font-size:13px;font-weight:600')} hover="background:var(--panel-2)"><Svg size={15} sw={2.2} d={PLUS} />Add Supplier</Box>
          <Box as="button" onClick={m.setRfqs} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13px;font-weight:600;box-shadow:var(--shadow-sm)')} hover="background:var(--primary-2)"><Svg size={15} fill d={SPARKLE_SM} />Generate RFQs</Box>
          <Box as="button" onClick={() => { if (window.confirm(`Delete “${m.activeProject.name}”? This permanently removes its documents, quotes and RFQs.`)) m.deleteProject(m.projectId) }} title="Delete project" style={css('display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:9px;background:var(--panel);border:1px solid var(--border);color:var(--text-3)')} hover="background:var(--danger-soft,rgba(220,38,38,.12));color:var(--danger);border-color:var(--danger)"><Svg size={15} sw={1.9} d={TRASH} /></Box>
        </div>
      </div>

      <div style={css('display:flex;border-bottom:1px solid var(--border);margin-bottom:22px;overflow-x:auto')}>
        <button onClick={m.setOverview} style={m.tabStyle.overview}><Svg size={15} sw={1.9} d='<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>' />Overview</button>
        <button onClick={m.setDocuments} style={m.tabStyle.documents}><Svg size={15} sw={1.9} d='M14 3v5h5" /><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z' />Documents</button>
        <button onClick={m.setSuppliers} style={m.tabStyle.suppliers}><Svg size={15} sw={1.9} d='<rect x="5" y="3" width="14" height="18" rx="1.6"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M10 21v-3h4v3"/>' />Suppliers</button>
        <button onClick={m.setRfqs} style={m.tabStyle.rfqs}><Svg size={15} sw={1.9} d='<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 7 8.5 5.5L20.5 7"/>' />RFQs</button>
        <button onClick={m.setQuotes} style={m.tabStyle.quotes}><Svg size={15} sw={1.9} d='M12 3v18M6 21h12" /><path d="M5 8h14" /><path d="m5 8-2.3 5a3 3 0 0 0 5.6 0z" /><path d="m19 8 2.3 5a3 3 0 0 1-5.6 0z' />Quotes</button>
        <button onClick={m.setTimeline} style={m.tabStyle.timeline}><Svg size={15} sw={1.9} d='M4 7h9M4 12h13M4 17h6' />Timeline</button>
      </div>

      {m.tabOverview && <TabOverview m={m} />}
      {m.tabDocuments && <TabDocuments m={m} />}
      {m.tabSuppliers && <TabSuppliers m={m} />}
      {m.tabRfqs && <TabRfqs m={m} />}
      {m.tabQuotesTable && <TabQuotes m={m} />}
      {m.tabCompare && <TabCompare m={m} />}
      {m.tabTimeline && <TabTimeline m={m} />}
    </div>
  )
}

/* ------------------------------------------------------------ Overview tab */
function TabOverview({ m }: MProps) {
  // In-place refresh of the activity stream (re-fetches the workspace bundle and
  // re-renders — no full page reload). Spins the icon while the fetch is in flight.
  const [refreshing, setRefreshing] = useState(false)
  const refresh = async () => {
    if (refreshing) return
    setRefreshing(true)
    try { await m.reload() } finally { setRefreshing(false) }
  }
  return (
    <>
      {m.overviewCards.length > 0 && (
      <div style={css('display:grid;grid-template-columns:repeat(auto-fit,minmax(162px,1fr));gap:13px;margin-bottom:18px')}>
        {m.overviewCards.map((c, i) => (
          <div key={i} style={css('background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:15px 16px;box-shadow:var(--shadow-sm);display:flex;flex-direction:column;gap:10px')}>
            <div style={css('display:flex;align-items:center;justify-content:space-between')}>
              <div style={c.chipStyle}><IconHtml html={c.iconHtml} /></div>
              {c.ai && <span style={css('font-size:10px;font-weight:700;color:var(--primary);background:var(--primary-soft);padding:2px 6px;border-radius:5px')}>AI</span>}
            </div>
            <div><div style={css("font-size:23px;font-weight:700;letter-spacing:-.02em;font-family:'JetBrains Mono',monospace")}>{c.value}</div><div style={css('font-size:12.5px;color:var(--text-2);font-weight:500;margin-top:1px')}>{c.label}</div></div>
            <div style={css('font-size:11.5px;color:var(--text-3)')}>{c.sub}</div>
          </div>
        ))}
      </div>
      )}
      {m.packages.length > 0 && (
      <div style={css('margin-bottom:16px')}>
        <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:18px')}>
          <h2 style={css('margin:0 0 16px;font-size:15px;font-weight:600')}>Procurement progress by package</h2>
          <div style={css('display:flex;flex-direction:column;gap:15px')}>
            {m.packages.map((p, i) => (
              <div key={i}>
                <div style={css('display:flex;align-items:center;justify-content:space-between;font-size:13px;margin-bottom:7px')}><span style={css('font-weight:500')}>{p.name}</span><span style={css("font-weight:600;font-family:'JetBrains Mono',monospace")}>{p.pct}%</span></div>
                <div style={css('height:8px;border-radius:999px;background:var(--panel-3);overflow:hidden')}><div style={p.barStyle}></div></div>
              </div>
            ))}
          </div>
        </div>
      </div>
      )}
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
        <div style={css('display:flex;align-items:center;justify-content:space-between;gap:10px;padding:15px 18px;border-bottom:1px solid var(--border)')}>
          <h2 style={css('margin:0;font-size:15px;font-weight:600')}>Recent project activity</h2>
          <Box as="button" onClick={refresh} title="Refresh activity" style={css('display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 11px;border-radius:8px;background:var(--panel);border:1px solid var(--border);color:var(--text-2);font-size:12.5px;font-weight:600;cursor:pointer')} hover="background:var(--panel-2)">
            <span style={css(refreshing ? 'display:inline-flex;animation:pcSpin .7s linear infinite' : 'display:inline-flex')}><IconHtml html={ic('refresh')} /></span>
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </Box>
        </div>
        <div style={css('padding:6px 8px')}>
          {m.projectActivity.map((a, i) => (
            <Box key={i} style={css('display:flex;gap:11px;padding:10px;border-radius:10px')} hover="background:var(--panel-2)">
              <div style={a.chipStyle}><IconHtml html={a.iconHtml} /></div>
              <div style={css('flex:1;min-width:0')}><div style={css('font-size:13px;font-weight:500')}>{a.title}</div><div style={css('font-size:11.5px;color:var(--text-3);margin-top:1px')}>{a.meta}</div></div>
              <span style={css('font-size:11px;color:var(--text-3);white-space:nowrap')}>{a.time}</span>
            </Box>
          ))}
          {m.projectActivity.length === 0 && (
            <div style={css('padding:28px 12px;text-align:center;font-size:12.5px;color:var(--text-3)')}>No activity yet — upload plans and send RFQs to see updates here.</div>
          )}
        </div>
      </div>
    </>
  )
}

/* ----------------------------------------------------------- Documents tab */
// Inline svg path data for the icons reused across the slot cards.
const UPLOAD_ICON = 'M12 16V4M7 9l5-5 5 5" /><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2'
const FILE_ICON = 'M14 3v5h5" /><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z'

type Slot = Model['docSlots'][number]

// One plan slot — holds a single site / building / electrical plan. A filled slot
// shows the document with View / Replace / Remove; an empty slot is an uploader.
// "Replace" re-uploads the same plan type, which the backend swaps in place.
function PlanSlotCard({ m, slot }: { m: Model; slot: Slot }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const pick = () => inputRef.current && inputRef.current.click()
  const onFiles = (fl: FileList | null) => {
    const f = fl && fl[0]
    if (f) m.onUpload(f, slot.key)
  }
  const d = slot.doc
  const active = !!(d && d.active)
  const btn = css('flex:1;height:30px;border-radius:7px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center')
  return (
    <div style={css(`background:var(--panel);border:1px solid ${active ? 'var(--primary)' : 'var(--border)'};border-radius:14px;box-shadow:var(--shadow-sm);padding:14px;display:flex;flex-direction:column;gap:10px;min-height:140px`)}>
      <input ref={inputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" style={{ display: 'none' }}
        onChange={(e) => { onFiles(e.target.files); e.target.value = '' }} />
      <div style={css('display:flex;align-items:center;gap:8px')}>
        <span style={css('width:26px;height:26px;border-radius:7px;background:var(--primary-soft);color:var(--primary);display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={14} sw={1.8} d={FILE_ICON} /></span>
        <span style={css('font-size:13px;font-weight:600;flex:1')}>{slot.label}</span>
        {d && <span style={d.statusBadge}>{d.processing && <span style={css('width:9px;height:9px;border:1.5px solid var(--primary);border-top-color:transparent;border-radius:50%;display:inline-block;animation:pcSpin .7s linear infinite')}></span>}{d.status}</span>}
      </div>
      {d ? (
        <>
          <Box onClick={d.onOpen} style={css('display:flex;flex-direction:column;gap:3px;cursor:pointer;flex:1')}>
            <span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{d.name}</span>
            <span style={css('font-size:11.5px;color:var(--text-3)')}>{d.date}{slot.categories.length ? ` · ${d.items} line items` : ''}</span>
          </Box>
          <div style={css('display:flex;gap:6px')}>
            <Box as="button" onClick={d.onOpen} style={btn} hover="background:var(--panel-2)">View</Box>
            <Box as="button" onClick={pick} disabled={m.uploading} style={btn} hover="background:var(--panel-2)">Replace</Box>
            <Box as="button" onClick={() => d.id && m.onDeleteDoc(d.id)} title="Remove" style={css('width:30px;height:30px;flex:none;border-radius:7px;border:1px solid var(--border);color:var(--text-3);display:flex;align-items:center;justify-content:center')} hover="background:var(--danger-soft);color:var(--danger)"><Svg size={14} sw={2.2} d="M18 6 6 18M6 6l12 12" /></Box>
          </div>
        </>
      ) : (
        <Box as="button" onClick={pick} disabled={m.uploading}
          style={css(`flex:1;border:1.5px dashed var(--border-strong);border-radius:10px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;color:var(--text-3);min-height:70px;opacity:${m.uploading ? '.6' : '1'}`)}
          hover="border-color:var(--primary);color:var(--primary);background:var(--primary-softer)">
          <Svg size={18} d={UPLOAD_ICON} />
          <span style={css('font-size:12px;font-weight:600')}>Upload {slot.label}</span>
        </Box>
      )}
    </div>
  )
}

// The non-slot bucket: any number of supporting reference documents. No BOM is
// extracted for these — they're stored as attachments.
function AdditionalDocsCard({ m }: MProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const pick = () => inputRef.current && inputRef.current.click()
  const onFiles = (fl: FileList | null) => {
    const f = fl && fl[0]
    if (f) m.onUpload(f, m.additionalKey)
  }
  return (
    <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden;margin-bottom:18px')}>
      <input ref={inputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" style={{ display: 'none' }}
        onChange={(e) => { onFiles(e.target.files); e.target.value = '' }} />
      <div style={css('display:flex;align-items:center;justify-content:space-between;padding:13px 16px;border-bottom:1px solid var(--border)')}>
        <div style={css('display:flex;align-items:center;gap:8px')}>
          <h2 style={css('margin:0;font-size:14px;font-weight:600')}>Additional documents</h2>
          <span style={css('font-size:12px;color:var(--text-3)')}>{m.additionalDocs.length} files</span>
        </div>
        <Box as="button" onClick={pick} disabled={m.uploading}
          style={css(`display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border-radius:8px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:12.5px;font-weight:600;opacity:${m.uploading ? '.6' : '1'}`)}
          hover="background:var(--panel-2)"><Svg size={14} sw={2.2} d={PLUS} />Add document</Box>
      </div>
      {m.additionalDocs.length === 0 ? (
        <div style={css('padding:20px 16px;font-size:12.5px;color:var(--text-3);text-align:center')}>No additional documents — add specs, geotech reports, or addenda for reference.</div>
      ) : (
        m.additionalDocs.map((d, i) => (
          <div key={d.id || i} onClick={d.onOpen} style={css(`display:grid;grid-template-columns:minmax(120px,2fr) 116px 104px 34px;gap:10px;align-items:center;padding:11px 16px;cursor:pointer;border-bottom:1px solid var(--border);background:${d.active ? 'var(--primary-softer)' : 'transparent'}`)}>
            <div style={css('display:flex;align-items:center;gap:9px;min-width:0')}><span style={css('width:28px;height:28px;border-radius:7px;background:var(--panel-3);color:var(--text-2);display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={14} sw={1.8} d={FILE_ICON} /></span><span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{d.name}</span></div>
            <span style={css('font-size:12px;color:var(--text-2)')}>{d.date}</span>
            <span><span style={d.statusBadge}>{d.status}</span></span>
            <Box as="button" onClick={(e: MouseEvent) => { e.stopPropagation(); d.id && m.onDeleteDoc(d.id) }} title="Remove" style={css('width:28px;height:28px;flex:none;border-radius:7px;color:var(--text-3);display:flex;align-items:center;justify-content:center')} hover="background:var(--danger-soft);color:var(--danger)"><Svg size={14} sw={2.2} d="M18 6 6 18M6 6l12 12" /></Box>
          </div>
        ))
      )}
    </div>
  )
}

// Hand-built bills of materials: create a named BOM, fill it in with the same
// editor the extracted BOMs use, then quote it from the Suppliers tab. Replaces
// the old throwaway free-text ad-hoc RFQ with a saved, viewable BOM.
function CustomBomsCard({ m }: MProps) {
  return (
    <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden;margin-bottom:18px')}>
      <div style={css('display:flex;align-items:center;justify-content:space-between;padding:13px 16px;border-bottom:1px solid var(--border)')}>
        <div style={css('display:flex;align-items:center;gap:8px')}>
          <h2 style={css('margin:0;font-size:14px;font-weight:600')}>Custom bills of materials</h2>
          <span style={css('font-size:12px;color:var(--text-3)')}>{m.customBoms.length}</span>
        </div>
        <Box as="button" onClick={m.createBom}
          style={css('display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border-radius:8px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:12.5px;font-weight:600')}
          hover="background:var(--panel-2)"><Svg size={14} sw={2.2} d={PLUS} />New BOM</Box>
      </div>
      {m.customBoms.length === 0 ? (
        <div style={css('padding:20px 16px;font-size:12.5px;color:var(--text-3);text-align:center')}>No custom BOMs yet — build one by hand for items not on a plan, then quote it from the Suppliers tab.</div>
      ) : (
        m.customBoms.map((d, i) => (
          <div key={d.id || i} onClick={d.onOpen} style={css(`display:grid;grid-template-columns:minmax(120px,2fr) 116px 104px 34px;gap:10px;align-items:center;padding:11px 16px;cursor:pointer;border-bottom:1px solid var(--border);background:${d.active ? 'var(--primary-softer)' : 'transparent'}`)}>
            <div style={css('display:flex;align-items:center;gap:9px;min-width:0')}><span style={css('width:28px;height:28px;border-radius:7px;background:var(--primary-soft);color:var(--primary);display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={14} sw={1.8} d='M9 3H5a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 5 21h14a1.5 1.5 0 0 0 1.5-1.5V4.5A1.5 1.5 0 0 0 19 3h-4" /><path d="M8 8h8M8 12h8M8 16h5' /></span><span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{d.name}</span></div>
            <span style={css('font-size:12px;color:var(--text-2)')}>{d.items === '—' ? '0' : d.items} items</span>
            <span><span style={d.statusBadge}>{d.status}</span></span>
            <Box as="button" onClick={(e: MouseEvent) => { e.stopPropagation(); d.id && m.onDeleteDoc(d.id) }} title="Remove" style={css('width:28px;height:28px;flex:none;border-radius:7px;color:var(--text-3);display:flex;align-items:center;justify-content:center')} hover="background:var(--danger-soft);color:var(--danger)"><Svg size={14} sw={2.2} d="M18 6 6 18M6 6l12 12" /></Box>
          </div>
        ))
      )}
    </div>
  )
}

// Derive the preview filename shown on the plan-sheet placeholder from the
// selected document's name, so the preview reflects the clicked document.
function previewFileName(name: string): string {
  const trimmed = (name || '').trim()
  if (!trimmed) return 'document.pdf'
  if (/\.[a-z0-9]+$/i.test(trimmed)) return trimmed
  const slug = trimmed
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return `${slug || 'document'}.pdf`
}

function TabDocuments({ m }: MProps) {
  // Custom BOMs have no source file — skip the plan-sheet / PDF preview and show
  // a simple card; the line items are edited in the panel on the right.
  const isCustomBom = !!(m.doc && m.doc.planType === m.customBomType)
  return (
    <>
      <div style={css('margin-bottom:6px;font-size:12.5px;color:var(--text-3)')}>
        {m.uploadError
          ? <span style={css('color:var(--danger)')}>{m.uploadError}</span>
          : m.uploading
            ? 'Uploading & extracting…'
            : 'One site, building, and electrical plan per project · GPT-4.1 extracts a Bill of Materials per discipline.'}
      </div>
      <div style={css('display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-bottom:18px')}>
        {m.docSlots.map((slot) => <PlanSlotCard key={slot.key} m={m} slot={slot} />)}
      </div>
      <CustomBomsCard m={m} />
      <AdditionalDocsCard m={m} />
      {m.doc && !m.doc.processing && (m.doc.timelineEvents || 0) > 0 && (
        <div style={css('display:flex;align-items:center;gap:10px;background:var(--primary-soft);border:1px solid var(--border);border-radius:12px;padding:10px 14px;margin-bottom:16px')}>
          <span style={css('width:24px;height:24px;border-radius:7px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={13} fill d={SPARKLE_SM} /></span>
          <span style={css('flex:1;font-size:12.5px')}><b>{m.doc.name}</b> added {m.doc.timelineEvents} schedule event{m.doc.timelineEvents === 1 ? '' : 's'} to the project timeline.</span>
          <Box as="button" onClick={m.setTimeline} style={css('font-size:12px;font-weight:600;color:var(--primary);padding:5px 11px;border-radius:8px;border:1px solid var(--border);background:var(--panel);white-space:nowrap')} hover="background:var(--primary-softer)">View timeline →</Box>
        </div>
      )}
      <div style={css('display:grid;grid-template-columns:minmax(0,1.7fr) 330px;gap:16px;align-items:start')}>
        <div style={css('display:flex;flex-direction:column;gap:16px;min-width:0')}>
          {m.doc && isCustomBom ? (
          <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
            <div style={css('display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border)')}>
              <div style={css('display:flex;align-items:center;gap:9px;min-width:0')}><span style={css('font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{m.doc.name}</span><span style={css('font-size:12px;color:var(--text-3);white-space:nowrap')}>{m.doc.items === '—' ? '0' : m.doc.items} line items</span></div>
              <span style={css('display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;color:var(--primary);background:var(--primary-soft);padding:3px 9px;border-radius:999px')}>Custom BOM</span>
            </div>
            <div style={css('padding:44px 24px;display:flex;flex-direction:column;align-items:center;gap:12px;text-align:center')}>
              <span style={css('width:48px;height:48px;border-radius:12px;background:var(--primary-soft);color:var(--primary);display:flex;align-items:center;justify-content:center')}><Svg size={24} sw={1.7} d='M9 3H5a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 5 21h14a1.5 1.5 0 0 0 1.5-1.5V4.5A1.5 1.5 0 0 0 19 3h-4" /><path d="M8 8h8M8 12h8M8 16h5' /></span>
              <div style={css('font-size:14px;font-weight:600')}>Hand-built bill of materials</div>
              <div style={css('font-size:12.5px;color:var(--text-3);max-width:340px')}>No plan to preview — add and edit line items in the panel on the right, then quote it from the Suppliers tab.</div>
            </div>
          </div>
          ) : m.doc ? (
          <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
            <div style={css('display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border)')}>
              <div style={css('display:flex;align-items:center;gap:9px;min-width:0')}><span style={css('font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{m.doc.name}</span><span style={css('font-size:12px;color:var(--text-3);white-space:nowrap')}>{m.doc.pages} pages</span></div>
              <span style={css('display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;color:var(--primary);background:var(--primary-soft);padding:3px 9px;border-radius:999px')}><Svg size={12} fill d={SPARKLE_SM} />AI Analysis</span>
            </div>
            <div style={css('position:relative;height:560px;background:repeating-linear-gradient(45deg,var(--panel-2),var(--panel-2) 12px,var(--panel-3) 12px,var(--panel-3) 24px);display:flex;align-items:center;justify-content:center')}>
              {m.doc.hasFile && m.doc.id ? (
                <DocPreviewFrame docId={m.doc.id} title={m.doc.name} />
              ) : (
                <span style={css("font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-3);background:var(--panel);padding:6px 12px;border-radius:8px;border:1px solid var(--border)")}>{previewFileName(m.doc.name)}</span>
              )}
              {m.doc.items && m.doc.items !== '—' && (
              <div style={css('position:absolute;left:18px;bottom:18px;display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--border);box-shadow:var(--shadow-md);padding:8px 12px;border-radius:10px;pointer-events:none')}><span style={css('width:24px;height:24px;border-radius:6px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center')}><Svg size={13} fill d={SPARKLE_SM} /></span><span style={css('font-size:12.5px;font-weight:600')}>AI detected <span style={css('color:var(--primary)')}>{m.doc.items}</span> line items</span></div>
              )}
            </div>
          </div>
          ) : (
          <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:40px 16px;text-align:center;font-size:12.5px;color:var(--text-3)')}>No document selected — upload a plan set or pick a file above to see its AI analysis.</div>
          )}
        </div>
        <ExtractedPanel m={m} />
      </div>
    </>
  )
}

/* Signed-URL document preview: iframes can't send the Authorization header, so
   the backend mints a short-lived scoped URL we resolve before rendering. */
function DocPreviewFrame({ docId, title }: { docId: string; title: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let alive = true
    setUrl(null); setFailed(false)
    getDocumentFileUrl(docId).then(
      (u) => { if (alive) setUrl(u) },
      () => { if (alive) setFailed(true) },
    )
    return () => { alive = false }
  }, [docId])
  if (failed) return <span style={css("font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-3);background:var(--panel);padding:6px 12px;border-radius:8px;border:1px solid var(--border)")}>Preview unavailable</span>
  if (!url) return <span style={css('font-size:12px;color:var(--text-3)')}>Loading preview…</span>
  return <iframe src={url} title={title} style={{ width: '100%', height: '100%', border: 'none', background: 'var(--panel)' }} />
}

/* ------------------------------- AI-extracted materials (human-in-the-loop) */
function ExtractedPanel({ m }: MProps) {
  const editing = m.bomEditing
  // In edit mode we render the draft (plain BOM groups); otherwise the extracted
  // groups, which carry presentational extras (dotStyle/countBadge).
  const groups = (editing ? m.bomDraft : m.extracted) as BomGroup[]
  const reviewed = m.doc && m.doc.reviewed
  const isCustom = !!(m.doc && m.doc.planType === m.customBomType)
  const inputCss = css('flex:1;min-width:0;font-size:12px;padding:5px 7px;border-radius:6px;border:1px solid var(--border);background:var(--panel-2);color:var(--text)')

  return (
    <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);position:sticky;top:72px;overflow:hidden')}>
      <div style={css('padding:14px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px')}>
        <span style={css('width:24px;height:24px;border-radius:7px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={14} fill d={SPARKLE_SM} /></span>
        <h2 style={css('margin:0;font-size:14px;font-weight:600;flex:1')}>{editing ? 'Edit materials' : isCustom ? 'Bill of materials' : 'Extracted materials'}</h2>
        {!editing && reviewed && (
          <span style={css('display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:var(--success);background:var(--success-soft);padding:3px 8px;border-radius:999px')}><Svg size={12} sw={2.4} d="M20 6 9 17l-5-5" />{isCustom ? 'Saved' : 'Confirmed'}</span>
        )}
        {!editing && (
          <Box as="button" onClick={m.startBomEdit} style={css('font-size:12px;font-weight:600;color:var(--text-2);padding:4px 9px;border-radius:7px;border:1px solid var(--border)')} hover="background:var(--panel-2)">Edit</Box>
        )}
        {editing && (
          <div style={css('display:flex;gap:6px')}>
            <Box as="button" onClick={m.cancelBomEdit} disabled={m.bomBusy} style={css('font-size:12px;font-weight:600;color:var(--text-2);padding:4px 9px;border-radius:7px;border:1px solid var(--border)')} hover="background:var(--panel-2)">Cancel</Box>
            <Box as="button" onClick={m.saveBom} disabled={m.bomBusy} style={css(`font-size:12px;font-weight:600;color:#fff;background:var(--primary);padding:4px 11px;border-radius:7px;opacity:${m.bomBusy ? '.6' : '1'}`)} hover="background:var(--primary-2)">{m.bomBusy ? 'Saving…' : 'Save'}</Box>
          </div>
        )}
      </div>

      <div style={css('max-height:520px;overflow-y:auto')}>
        {groups.length === 0 && (
          <div style={css('padding:22px 16px;font-size:12.5px;color:var(--text-3);text-align:center')}>No materials yet — still processing, or none were found on this document.</div>
        )}
        {groups.map((g, i) => (
          <div key={i} style={css('padding:13px 16px;border-bottom:1px solid var(--border)')}>
            <div style={css('display:flex;align-items:center;gap:8px;margin-bottom:9px')}>
              <span style={g.dotStyle || css('width:8px;height:8px;border-radius:2px;background:var(--text-3);flex:none')}></span>
              <span style={css('font-size:12.5px;font-weight:600;flex:1')}>{g.group}</span>
              <span style={g.countBadge || css('font-size:11px;font-weight:600;color:var(--text-3)')}>{editing ? g.items.length : g.count}</span>
            </div>
            <div style={css('display:flex;flex-direction:column;gap:6px')}>
              {g.items.map((it, j) => (editing ? (
                <div key={j} style={css('display:flex;align-items:center;gap:6px')}>
                  <input value={it.n} placeholder="Material" onChange={(e) => m.editBomItem(i, j, 'n', e.target.value)} style={inputCss} />
                  <input value={it.q} placeholder="Qty" onChange={(e) => m.editBomItem(i, j, 'q', e.target.value)} style={css("width:78px;flex:none;font-size:12px;padding:5px 7px;border-radius:6px;border:1px solid var(--border);background:var(--panel-2);color:var(--text);font-family:'JetBrains Mono',monospace")} />
                  <Box as="button" onClick={() => m.deleteBomItem(i, j)} title="Remove" style={css('width:24px;height:24px;flex:none;border-radius:6px;color:var(--text-3);display:flex;align-items:center;justify-content:center')} hover="background:var(--danger-soft);color:var(--danger)"><Svg size={14} sw={2.2} d="M18 6 6 18M6 6l12 12" /></Box>
                </div>
              ) : (
                <div key={j} style={css('display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:12px')}><span style={css('color:var(--text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{it.n}</span><span style={css("font-weight:600;font-family:'JetBrains Mono',monospace;white-space:nowrap")}>{it.q}</span></div>
              )))}
            </div>
            {editing && (
              <Box as="button" onClick={() => m.addBomItem(i)} style={css('margin-top:8px;font-size:11.5px;font-weight:600;color:var(--primary);display:inline-flex;align-items:center;gap:4px;padding:3px 6px;border-radius:6px')} hover="background:var(--primary-soft)"><Svg size={13} sw={2.2} d="M12 5v14M5 12h14" />Add item</Box>
            )}
          </div>
        ))}
      </div>

      {!editing && groups.length > 0 && (
        <div style={css('padding:12px 16px;border-top:1px solid var(--border)')}>
          {reviewed ? (
            <div style={css('font-size:11.5px;color:var(--text-3)')}>Reviewed by you{m.doc.reviewedAt ? ` · ${m.doc.reviewedAt}` : ''}. Edit to revise.</div>
          ) : (
            <Box as="button" onClick={m.confirmBom} disabled={m.bomBusy} style={css(`width:100%;height:34px;border-radius:8px;background:var(--success);color:#fff;font-size:12.5px;font-weight:600;display:flex;align-items:center;justify-content:center;gap:6px;opacity:${m.bomBusy ? '.6' : '1'}`)} hover="filter:brightness(1.05)"><Svg size={14} sw={2.4} d="M20 6 9 17l-5-5" />{m.bomBusy ? 'Working…' : 'Confirm BOM'}</Box>
          )}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------ Suppliers tab (project) */
// Buy-packages the BOM is grouped into, by plan discipline (mirrors the backend
// sourcing.packages + the extraction plan_types). Each key matches a backend
// package key so the supplier search / RFQ generation routes accept it directly.
const PACKAGE_GROUPS = [
  {
    label: 'Site / Civil',
    packages: [
      { key: 'water', label: 'Water Utilities' },
      { key: 'sewer', label: 'Sanitary Sewer' },
      { key: 'storm', label: 'Storm Drain' },
      { key: 'erosion', label: 'Erosion Control' },
    ],
  },
  {
    label: 'Building / Structural',
    packages: [
      { key: 'concrete', label: 'Cast-in-Place Concrete' },
      { key: 'rebar', label: 'Reinforcing Steel' },
      { key: 'steel', label: 'Structural Steel' },
      { key: 'masonry', label: 'Masonry' },
      { key: 'framing', label: 'Wood & Framing' },
    ],
  },
  {
    label: 'Electrical',
    packages: [
      { key: 'raceway', label: 'Conduit & Raceway' },
      { key: 'conductors', label: 'Wire & Cable' },
      { key: 'equipment', label: 'Panels & Distribution' },
      { key: 'devices', label: 'Devices & Rough-in' },
      { key: 'lighting', label: 'Lighting Fixtures' },
      { key: 'grounding', label: 'Grounding & Bonding' },
      { key: 'lowvoltage', label: 'Low-Voltage & Fire Alarm' },
    ],
  },
]

const BUY_PACKAGES = PACKAGE_GROUPS.flatMap((g) => g.packages)

const TIER_TONE: Record<number, string> = { 1: 'success', 2: 'blue', 3: 'violet' }

function pkgLabel(key: string): string {
  if (key === 'adhoc') return 'Ad-hoc RFQ'
  const p = BUY_PACKAGES.find((x) => x.key === key)
  return p ? p.label : key
}

// Self-contained supplier search: pick a discipline buy-package or a hand-built
// custom BOM, set a radius, search Google Places (mock when no key), review
// tiered results, select recipients, and generate an RFQ draft. Custom BOMs are
// created in the Documents panel and selected here by their document id — they
// quote exactly like a package (replacing the old free-text ad-hoc flow).
// Manages its own state + polling.
function SupplierSearch({ projectId, networkNames, onAdded }: { projectId: string; networkNames: Set<string>; onAdded: () => void | Promise<void> }) {
  const [pkg, setPkg] = useState('water')
  const [radius, setRadius] = useState(75)
  const [boms, setBoms] = useState<CustomBomSummary[]>([])     // custom BOMs on this project
  const [result, setResult] = useState<SupplierSearchResult | null>(null)
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [draft, setDraft] = useState<PersistedRfq | null>(null)
  const [generating, setGenerating] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [bom, setBom] = useState<PackageBom | null>(null)   // what we're asking suppliers to quote
  const [bomLoading, setBomLoading] = useState(false)
  const [savingId, setSavingId] = useState<string | null>(null)   // found supplier currently being added

  // Resolve a package key — a preset key or a custom BOM's document id — to its
  // display label. Custom BOMs show their own name.
  const labelFor = (key: string) => boms.find((b) => b.id === key)?.name || pkgLabel(key)
  const subjectLabel = labelFor(pkg)
  const isCustom = !!(bom && bom.custom)

  // Load this project's custom BOMs (the extra selectable "packages").
  useEffect(() => {
    let alive = true
    listProjectBoms(projectId).then((b) => { if (alive) setBoms(b) }).catch(() => {})
    return () => { alive = false }
  }, [projectId])

  // Load any prior results when the package changes.
  useEffect(() => {
    let alive = true
    setResult(null); setSelected({}); setErr(null)
    getFoundSuppliers(projectId, pkg)
      .then((r) => { if (!alive) return; setResult(r); if (r.status === 'searching') setSearching(true) })
      .catch(() => {})
    return () => { alive = false }
  }, [projectId, pkg])

  // Load the selected package/BOM's line items (what we'll ask suppliers to quote).
  useEffect(() => {
    let alive = true
    setBom(null); setBomLoading(true)
    getPackageBom(projectId, pkg)
      .then((b) => { if (alive) setBom(b) })
      .catch(() => {})
      .finally(() => { if (alive) setBomLoading(false) })
    return () => { alive = false }
  }, [projectId, pkg])

  // Poll while a background search runs.
  useEffect(() => {
    if (!searching) return
    const t = setInterval(() => {
      getFoundSuppliers(projectId, pkg)
        .then((r) => { setResult(r); if (r.status !== 'searching') setSearching(false) })
        .catch(() => {})
    }, 2500)
    return () => clearInterval(t)
  }, [searching, projectId, pkg])

  const runSearch = async () => {
    setErr(null); setSelected({})
    try {
      await searchSuppliers(projectId, pkg, radius)
      setSearching(true)
      setResult({ status: 'searching', mocked: false, radiusMi: radius, package: pkg, error: null, tiers: [] })
    } catch (e) { setErr('Search failed. Is the backend running?') }
  }

  const toggle = (id: string) => setSelected((s) => ({ ...s, [id]: !s[id] }))
  const selectedIds = Object.keys(selected).filter((k) => selected[k])

  // Whether a found supplier is already in the customer's network (by name).
  const inNetwork = (sup: FoundSupplier) => networkNames.has(sup.name.toLowerCase())

  // Add a discovered supplier to the customer's network, then refresh the list.
  const add = async (sup: FoundSupplier) => {
    setSavingId(sup.id); setErr(null)
    try {
      await createSupplier({
        name: sup.name,
        contact: sup.contactName || '',
        phone: sup.phone || '',
        email: sup.email || '',
        web: sup.website || '',
        cats: sup.materialCategories || [],
      })
      await onAdded()
    } catch { setErr('Could not add supplier — is the backend running?') }
    finally { setSavingId(null) }
  }

  const generate = async () => {
    setGenerating(true); setErr(null)
    try {
      const rfq = await generateRfq(projectId, pkg, selectedIds)
      setDraft(rfq)
    } catch (e) {
      // Surface backend reasons (e.g. the BOM approval gate: "confirm the
      // extracted BOM first") over the generic fallback.
      const msg = e instanceof Error && e.message && !e.message.includes('->') ? e.message : null
      setErr(msg || 'Could not generate RFQ — selected suppliers may not have a discovered email.')
    } finally { setGenerating(false) }
  }

  const tiers = (result && result.tiers) || []
  const total = tiers.reduce((n, t) => n + t.suppliers.length, 0)
  const chip = (active: boolean) =>
    css(`height:32px;padding:0 13px;border-radius:8px;font-size:12.5px;font-weight:600;border:1px solid ${active ? 'var(--primary)' : 'var(--border)'};background:${active ? 'var(--primary-soft)' : 'var(--panel)'};color:${active ? 'var(--primary)' : 'var(--text-2)'};display:inline-flex;align-items:center;gap:6px`)

  return (
    <>
      {/* Controls */}
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:16px 18px;margin-bottom:16px')}>
        <div style={css('display:flex;align-items:center;gap:8px;margin-bottom:13px')}>
          <span style={css('width:24px;height:24px;border-radius:7px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={14} fill d={SPARKLE_SM} /></span>
          <h2 style={css('margin:0;font-size:14px;font-weight:600;flex:1')}>Find suppliers near the jobsite</h2>
        </div>
        <div style={css('display:flex;flex-direction:column;gap:11px;margin-bottom:14px')}>
          {PACKAGE_GROUPS.map((g) => (
            <div key={g.label}>
              <div style={css('font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--text-3);margin-bottom:7px')}>{g.label}</div>
              <div style={css('display:flex;gap:7px;flex-wrap:wrap')}>
                {g.packages.map((p) => (
                  <Box as="button" key={p.key} onClick={() => setPkg(p.key)} style={chip(pkg === p.key)}
                    hover="background:var(--panel-2)">{p.label}</Box>
                ))}
              </div>
            </div>
          ))}
          <div>
            <div style={css('font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--text-3);margin-bottom:7px')}>Custom BOMs</div>
            <div style={css('display:flex;gap:7px;flex-wrap:wrap;align-items:center')}>
              {boms.map((b) => (
                <Box as="button" key={b.id} onClick={() => setPkg(b.id)} style={chip(pkg === b.id)} hover="background:var(--panel-2)">
                  <Svg size={13} sw={1.9} d='M9 3H5a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 5 21h14a1.5 1.5 0 0 0 1.5-1.5V4.5A1.5 1.5 0 0 0 19 3h-4" /><path d="M8 8h8M8 12h8M8 16h5' />{b.name}
                  <span style={css('font-size:11px;font-weight:700;color:var(--text-3)')}>{b.count}</span>
                </Box>
              ))}
              {boms.length === 0 && <span style={css('font-size:12px;color:var(--text-3)')}>None yet — create one in the Documents tab to quote items by hand.</span>}
            </div>
          </div>
        </div>

        <div style={css('display:flex;align-items:center;gap:16px;flex-wrap:wrap')}>
          <div style={css('display:flex;align-items:center;gap:11px;flex:1;min-width:240px')}>
            <span style={css('font-size:12.5px;font-weight:600;color:var(--text-2);white-space:nowrap')}>Search radius</span>
            <input type="range" min={5} max={250} step={5} value={radius}
              onChange={(e) => setRadius(Number(e.target.value))}
              style={{ flex: 1, accentColor: 'var(--primary)' }} />
            <span style={css("font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;background:var(--panel-2);border:1px solid var(--border);padding:4px 9px;border-radius:8px;white-space:nowrap")}>{radius} mi</span>
          </div>
          <Box as="button" onClick={runSearch} disabled={searching}
            style={css(`display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 16px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13px;font-weight:600;box-shadow:var(--shadow-sm);opacity:${searching ? '.6' : '1'}`)}
            hover="background:var(--primary-2)">
            {searching
              ? <span style={css('width:14px;height:14px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;display:inline-block;animation:pcSpin .7s linear infinite')}></span>
              : <Svg size={15} d='<circle cx="11" cy="11" r="7"/><path d="m20 20-3-3"/>' />}
            {searching ? 'Searching…' : 'Search suppliers'}
          </Box>
        </div>
        <div style={css('font-size:11.5px;color:var(--text-3);margin-top:10px')}>
          Tier 1 local (0–25 mi) · Tier 2 regional (25–75 mi) · Tier 3 manufacturers (75–250 mi). Distances are approximate (straight-line).
          {result && result.mocked && <span style={css('color:var(--warn);font-weight:600')}> · Showing mock results (no Google API key set)</span>}
        </div>
        {err && <div style={css('font-size:12.5px;color:var(--danger);margin-top:8px')}>{err}</div>}
      </div>

      {/* What we're asking suppliers to quote — the package's or custom BOM's items */}
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:16px 18px;margin-bottom:16px')}>
        <div style={css('display:flex;align-items:center;gap:9px;margin-bottom:4px')}>
          <h2 style={css('margin:0;font-size:14px;font-weight:600;flex:1')}>What we're asking for · {labelFor(pkg)}</h2>
          {bom && bom.count > 0 && <span style={{ ...DcBadge('blue') }}>{bom.count} item{bom.count > 1 ? 's' : ''}</span>}
        </div>
        <div style={css('font-size:11.5px;color:var(--text-3);margin-bottom:12px')}>
          {isCustom
            ? 'Your hand-built bill of materials — these line items go into the RFQ.'
            : "Pulled from this project's extracted plans — these line items go into the RFQ."}
          {bom && bom.seeded && <span style={css('color:var(--warn);font-weight:600')}> · Sample BOM (nothing extracted for this package yet)</span>}
        </div>
        {bomLoading && <div style={css('font-size:13px;color:var(--text-3);padding:8px 0')}>Loading BOM…</div>}
        {!bomLoading && bom && bom.count === 0 && (
          <div style={css('font-size:13px;color:var(--text-3);padding:8px 0')}>
            {isCustom
              ? 'This BOM has no items yet — add line items in the Documents tab, then come back to quote it.'
              : `No ${labelFor(pkg)} items found yet. Upload the relevant plan to extract this BOM, or build a custom BOM in the Documents tab.`}
          </div>
        )}
        {!bomLoading && bom && bom.count > 0 && (
          <div style={css('display:flex;flex-direction:column;border:1px solid var(--border);border-radius:11px;overflow:hidden')}>
            {bom.items.map((it, i) => (
              <div key={i} style={css(`display:flex;align-items:center;gap:12px;padding:9px 13px;font-size:13px;${i ? 'border-top:1px solid var(--border);' : ''}`)}>
                <span style={css('flex:1;min-width:0;color:var(--text)')}>{it.n}</span>
                <span style={css("font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:var(--text-2);white-space:nowrap")}>{it.q || '—'}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      {searching && total === 0 && (
        <div style={css('padding:30px;text-align:center;font-size:13px;color:var(--text-3)')}>Searching Google Places & discovering supplier emails…</div>
      )}
      {!searching && result && total === 0 && (
        <div style={css('padding:30px;text-align:center;font-size:13px;color:var(--text-3)')}>
          No suppliers found yet — run a search for {labelFor(pkg)}.
        </div>
      )}

      {tiers.map((t) => (
        <div key={t.tier} style={css('margin-bottom:18px')}>
          <div style={css('display:flex;align-items:center;gap:9px;margin-bottom:10px')}>
            <span style={{ ...DcBadge(TIER_TONE[t.tier] || 'gray') }}>Tier {t.tier}</span>
            <span style={css('font-size:13px;font-weight:600')}>{t.label}</span>
            <span style={css('font-size:11.5px;color:var(--text-3)')}>· {t.suppliers.length}</span>
          </div>
          <div style={css('display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px')}>
            {t.suppliers.map((sup) => (
              <FoundSupplierCard key={sup.id} sup={sup} checked={!!selected[sup.id]} onToggle={() => toggle(sup.id)}
                inNetwork={inNetwork(sup)} saving={savingId === sup.id} onAdd={() => add(sup)} />
            ))}
          </div>
        </div>
      ))}

      {/* Action bar */}
      {selectedIds.length > 0 && (
        <div style={css('position:sticky;bottom:14px;display:flex;align-items:center;gap:13px;background:var(--panel);border:1px solid var(--primary-soft);box-shadow:var(--shadow-md);border-radius:13px;padding:12px 16px;margin-top:8px')}>
          <span style={css('font-size:13px;font-weight:600;flex:1')}>{selectedIds.length} supplier{selectedIds.length > 1 ? 's' : ''} selected for {subjectLabel}</span>
          <Box as="button" onClick={generate} disabled={generating}
            style={css(`display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 16px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13px;font-weight:600;opacity:${generating ? '.6' : '1'}`)}
            hover="background:var(--primary-2)"><Svg size={15} fill d={SPARKLE_SM} />{generating ? 'Generating…' : 'Generate RFQ draft'}</Box>
        </div>
      )}

      {draft && (
        <RfqReviewModal projectId={projectId} rfq={draft} onClose={() => setDraft(null)} />
      )}
    </>
  )
}

// Small tone badge (mirrors the badge() helper without importing it here).
function DcBadge(t: string): CSSProperties {
  const map: Record<string, [string, string]> = {
    success: ['var(--success-soft)', 'var(--success)'],
    blue: ['var(--primary-soft)', 'var(--primary)'],
    violet: ['var(--violet-soft,#ede9fe)', 'var(--violet)'],
    warn: ['var(--warn-soft)', 'var(--warn)'],
    gray: ['var(--panel-3)', 'var(--text-2)'],
  }
  const [bg, fg] = map[t] || map.gray
  return css(`display:inline-flex;align-items:center;font-size:11px;font-weight:700;padding:2px 9px;border-radius:999px;background:${bg};color:${fg}`)
}

function FoundSupplierCard({ sup, checked, onToggle, inNetwork, saving, onAdd }: { sup: FoundSupplier; checked: boolean; onToggle: () => void; inNetwork: boolean; saving: boolean; onAdd: () => void }) {
  const hasEmail = !!sup.email
  return (
    <div style={css(`background:var(--panel);border:1px solid ${checked ? 'var(--primary)' : 'var(--border)'};border-radius:14px;padding:14px;box-shadow:var(--shadow-sm);display:flex;flex-direction:column;gap:9px`)}>
      <div style={css('display:flex;align-items:flex-start;gap:10px')}>
        <input type="checkbox" checked={checked} disabled={!hasEmail} onChange={onToggle}
          title={hasEmail ? 'Select for RFQ' : 'No email — cannot RFQ'}
          style={{ marginTop: 3, accentColor: 'var(--primary)', cursor: hasEmail ? 'pointer' : 'not-allowed' }} />
        <div style={css('flex:1;min-width:0')}>
          <div style={css('font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis')}>{sup.name}</div>
          <div style={css('font-size:11.5px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{sup.address}</div>
        </div>
        <span style={css("font-size:12px;font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--text-2);white-space:nowrap")}>~{sup.distanceMiles} mi</span>
      </div>
      <div style={css('display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--text-2);padding-top:9px;border-top:1px solid var(--border)')}>
        {sup.phone && <div style={css('display:flex;align-items:center;gap:7px')}><Svg size={13} sw={1.9} stroke="var(--text-3)" d='M5 4h3l2 5-2.5 1.5a11 11 0 0 0 5 5L14 13l5 2v3a2 2 0 0 1-2 2A15 15 0 0 1 3 6a2 2 0 0 1 2-2z' />{sup.phone}</div>}
        {hasEmail
          ? <div style={css('display:flex;align-items:center;gap:7px;overflow:hidden')}><Svg size={13} sw={1.9} stroke="var(--text-3)" d='<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 7 8.5 5.5L20.5 7"/>' /><span style={css('overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{sup.email}</span></div>
          : <div style={css('display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;color:var(--warn);background:var(--warn-soft);padding:2px 8px;border-radius:999px;align-self:flex-start')}>No email found</div>}
        {sup.website && <a href={sup.website} target="_blank" rel="noreferrer" style={css('display:flex;align-items:center;gap:7px;color:var(--primary);text-decoration:none;overflow:hidden')}><Svg size={13} sw={1.9} stroke="var(--primary)" d='<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z"/>' /><span style={css('overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{sup.website.replace(/^https?:\/\//, '')}</span></a>}
      </div>
      {inNetwork ? (
        <div style={css('display:inline-flex;align-items:center;justify-content:center;gap:6px;height:34px;border-radius:9px;background:var(--success-soft);color:var(--success);font-size:12.5px;font-weight:600')}>
          <Svg size={14} sw={2.2} d='m20 6-11 11-5-5' />In your network
        </div>
      ) : (
        <Box as="button" onClick={onAdd} disabled={saving}
          style={css(`display:inline-flex;align-items:center;justify-content:center;gap:6px;height:34px;border-radius:9px;background:var(--panel);border:1px solid var(--border-strong);color:var(--text);font-size:12.5px;font-weight:600;opacity:${saving ? '.6' : '1'}`)}
          hover="background:var(--panel-2);border-color:var(--primary);color:var(--primary)">
          {saving
            ? <span style={css('width:13px;height:13px;border:2px solid var(--text-3);border-top-color:transparent;border-radius:50%;display:inline-block;animation:pcSpin .7s linear infinite')}></span>
            : <Svg size={14} sw={2.2} d={PLUS} />}
          {saving ? 'Adding…' : 'Add to network'}
        </Box>
      )}
    </div>
  )
}

const STATUS_TONE: Record<string, string> = { Draft: 'gray', Sent: 'blue', Awaiting: 'warn', Quoted: 'success' }

// One message bubble in an RFQ email thread (outbound = us, inbound = supplier).
function ThreadBubble({ t }: { t: RfqConversation['thread'][number] }) {
  const out = t.dir === 'out'
  return (
    <div style={css('display:flex;gap:11px')}>
      <div style={css(`width:30px;height:30px;border-radius:50%;flex:none;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:#fff;background:${out ? 'linear-gradient(135deg,#2563eb,#7c3aed)' : (t.logoBg || '#334155')}`)}>{t.initials}</div>
      <div style={css('flex:1;min-width:0')}>
        <div style={css('display:flex;align-items:center;gap:8px;margin-bottom:4px')}><span style={css('font-size:12.5px;font-weight:600')}>{t.who}</span><span style={css('font-size:11px;color:var(--text-3)')}>{t.time}</span></div>
        {t.subject && <div style={css('font-size:13px;font-weight:600;margin-bottom:3px')}>{t.subject}</div>}
        <div style={css('font-size:13px;line-height:1.55;color:var(--text);white-space:pre-wrap;word-break:break-word')}>{t.body}</div>
        {t.attach && <div style={css('display:inline-flex;align-items:center;gap:7px;margin-top:8px;padding:7px 11px;border:1px solid var(--border);border-radius:9px;background:var(--panel-2);font-size:12px;font-weight:500')}><Svg size={14} sw={1.8} stroke="var(--text-3)" d='M21 8l-9 9a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8' />{t.attach}</div>}
      </div>
    </div>
  )
}

// Shared RFQ modal. A draft is editable and can be sent (the user-approval step,
// via Gmail or the logging mock). Once sent it becomes the conversation view:
// the full email thread is read live from Gmail, and "Check for replies" pulls
// any supplier response — flipping the RFQ to 'Replied' when one has arrived.
function RfqReviewModal({ projectId, rfq, onClose }: { projectId: string; rfq: PersistedRfq; onClose: () => void }) {
  const [subject, setSubject] = useState(rfq.subject)
  const [body, setBody] = useState(rfq.body)
  const [recipients, setRecipients] = useState<RfqRecipient[]>(rfq.recipients || [])
  const [status, setStatus] = useState(rfq.status)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [conv, setConv] = useState<RfqConversation | null>(null)
  const [loadingConv, setLoadingConv] = useState(false)
  const draft = status === 'Draft'

  const dropRecipient = (email: string) => setRecipients((rs) => rs.filter((r) => r.email !== email))

  const loadConversation = async () => {
    setLoadingConv(true); setErr(null)
    try {
      const c = await getRfqConversation(projectId, rfq.id)
      setConv(c)
      setStatus(c.status) // server may have flipped Awaiting → Replied
    } catch { setErr('Could not load the conversation. Is the backend running?') }
    finally { setLoadingConv(false) }
  }

  // Pull the thread as soon as a non-draft RFQ opens.
  useEffect(() => { if (!draft) loadConversation() }, [])

  const send = async () => {
    setBusy(true); setErr(null)
    try {
      await saveRfq(projectId, rfq.id, { subject, body, recipients })
      const out = await sendRfq(projectId, rfq.id)
      setRecipients(out.recipients || [])
      setStatus(out.status)
      loadConversation() // surface the just-sent message as the thread
    } catch (e) {
      // Backend reasons (already sent, no approved BOM items, …) come through
      // the error message; fall back to the generic hint otherwise.
      const msg = e instanceof Error && e.message && !e.message.includes('->') ? e.message : null
      setErr(msg || 'Send failed. Is the backend running?')
    }
    finally { setBusy(false) }
  }

  return (
    <div style={css('position:fixed;inset:0;z-index:80;display:flex;align-items:center;justify-content:center;padding:20px')}>
      <div onClick={onClose} style={css('position:absolute;inset:0;background:rgba(15,20,30,.45)')}></div>
      <div style={css('position:relative;width:min(640px,100%);max-height:90vh;overflow-y:auto;background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-lg);animation:pcUp .2s ease both')}>
        <div style={css('display:flex;align-items:center;gap:9px;padding:16px 18px;border-bottom:1px solid var(--border)')}>
          <span style={css('width:26px;height:26px;border-radius:7px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={15} fill d={SPARKLE_SM} /></span>
          <h2 style={css('margin:0;font-size:15px;font-weight:700;flex:1')}>{draft ? 'Review RFQ draft' : 'RFQ conversation'} · {rfq.pkg || pkgLabel(rfq.package)}</h2>
          {!draft && <span style={DcBadge(STATUS_TONE[status] || 'gray')}>{status}</span>}
          <Box as="button" onClick={onClose} style={css('width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--text-2)')} hover="background:var(--panel-2)"><Svg size={17} d='M6 6l12 12M18 6 6 18' /></Box>
        </div>
        <div style={css('padding:18px;display:flex;flex-direction:column;gap:16px')}>
          {draft && (
            <div>
              <label style={fieldLabel}>Subject</label>
              <input value={subject} onChange={(e) => setSubject(e.target.value)} style={fieldInput} />
            </div>
          )}
          <div>
            <label style={fieldLabel}>Recipients ({recipients.length})</label>
            <div style={css('display:flex;flex-direction:column;gap:6px')}>
              {recipients.length === 0 && <div style={css('font-size:12.5px;color:var(--text-3)')}>No recipients.</div>}
              {recipients.map((r) => (
                <div key={r.email} style={css('display:flex;align-items:center;gap:9px;padding:7px 11px;border:1px solid var(--border);border-radius:9px;background:var(--panel-2)')}>
                  <div style={css('flex:1;min-width:0')}><div style={css('font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{r.name}</div><div style={css('font-size:11.5px;color:var(--text-3)')}>{r.email}</div></div>
                  {r.sentMessageId
                    ? <span style={css(`font-size:11px;font-weight:600;color:${r.sentMessageId.startsWith('error') ? 'var(--danger)' : 'var(--success)'}`)}>{r.sentMessageId.startsWith('error') ? 'Failed' : 'Sent'}</span>
                    : draft && <Box as="button" onClick={() => dropRecipient(r.email)} style={css('width:24px;height:24px;border-radius:6px;color:var(--text-3);display:flex;align-items:center;justify-content:center')} hover="background:var(--danger-soft);color:var(--danger)"><Svg size={14} sw={2.2} d="M18 6 6 18M6 6l12 12" /></Box>}
                </div>
              ))}
            </div>
          </div>
          {draft ? (
            <div>
              <label style={fieldLabel}>Message</label>
              <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={12}
                style={{ ...css('width:100%;padding:11px 13px;border-radius:10px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:13px;line-height:1.55;resize:vertical;font-family:inherit') }} />
            </div>
          ) : (
            <div>
              <div style={css('display:flex;align-items:center;justify-content:space-between;margin-bottom:10px')}>
                <label style={{ ...fieldLabel, marginBottom: 0 }}>Conversation</label>
                <Box as="button" onClick={loadingConv ? undefined : loadConversation}
                  style={css(`display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 11px;border-radius:8px;border:1px solid var(--border);font-size:12px;font-weight:600;color:var(--text-2);${loadingConv ? 'opacity:.6' : ''}`)}
                  hover="background:var(--panel-2)"><Svg size={13} sw={2} d='M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5' />{loadingConv ? 'Checking…' : 'Check for replies'}</Box>
              </div>
              {conv && !conv.gmail && <div style={css('font-size:11.5px;color:var(--text-3);margin-bottom:10px')}>Showing a local preview — set Gmail credentials to read the live thread.</div>}
              <div style={css('display:flex;flex-direction:column;gap:16px;padding:14px;border:1px solid var(--border);border-radius:12px;background:var(--panel-2);max-height:340px;overflow-y:auto')}>
                {!conv && loadingConv && <div style={css('font-size:12.5px;color:var(--text-3);text-align:center;padding:18px')}>Loading conversation…</div>}
                {conv && conv.thread.length === 0 && <div style={css('font-size:12.5px;color:var(--text-3);text-align:center;padding:18px')}>No messages yet.</div>}
                {conv && conv.thread.map((t, i) => <ThreadBubble key={i} t={t} />)}
              </div>
            </div>
          )}
          {err && <div style={css('font-size:12.5px;color:var(--danger)')}>{err}</div>}
        </div>
        <div style={css('display:flex;align-items:center;gap:10px;padding:14px 18px;border-top:1px solid var(--border)')}>
          <span style={css('flex:1;font-size:11.5px;color:var(--text-3)')}>{draft ? 'Sending delivers to all recipients via Gmail (or a logging mock if unconfigured).' : 'The conversation is read live from Gmail — use Check for replies to refresh.'}</span>
          <Box as="button" onClick={onClose} style={css('height:36px;padding:0 14px;border-radius:9px;border:1px solid var(--border);font-size:13px;font-weight:600')} hover="background:var(--panel-2)">{draft ? 'Cancel' : 'Close'}</Box>
          {draft && (
            <Box as="button" onClick={send} disabled={busy || recipients.length === 0}
              style={css(`display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 16px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13px;font-weight:600;opacity:${busy || recipients.length === 0 ? '.6' : '1'}`)}
              hover="background:var(--primary-2)"><Svg size={15} d='M22 2 11 13M22 2l-7 20-4-9-9-4z' />{busy ? 'Sending…' : `Send RFQ (${recipients.length})`}</Box>
          )}
        </div>
      </div>
    </div>
  )
}

function TabSuppliers({ m }: MProps) {
  // Names already in the customer's network — the search marks matching results
  // as "In your network" and adding one refreshes the global list via m.reload.
  const networkNames = new Set<string>((m.suppliers || []).map((s) => s.name.toLowerCase()))
  return <SupplierSearch projectId={m.activeProject.id} networkNames={networkNames} onAdded={m.reload} />
}

/* ----------------------------------------------------------------- RFQs tab */
// The RFQs page lists the real RFQs generated from supplier search in an
// email-client layout: a status rail on the left filters the list, and clicking
// any row opens it in the review/send modal. Drafts can be deleted inline.
const RFQ_FOLDERS: { key: string; name: string }[] = [
  { key: 'All', name: 'All RFQs' },
  { key: 'Draft', name: 'Drafts' },
  { key: 'Awaiting', name: 'Awaiting Response' },
  { key: 'Sent', name: 'Sent' },
  { key: 'Quoted', name: 'Quoted' },
]

function TabRfqs({ m }: MProps) {
  const projectId = m.activeProject.id
  const [rfqs, setRfqs] = useState<PersistedRfq[] | null>(null)
  const [open, setOpen] = useState<PersistedRfq | null>(null)
  const [filter, setFilter] = useState('All')
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = () => listGeneratedRfqs(projectId).then(setRfqs).catch(() => setRfqs([]))
  useEffect(() => { load() }, [projectId])

  const all = rfqs || []
  const count = (key: string) => (key === 'All' ? all.length : all.filter((r) => r.status === key).length)
  const shown = filter === 'All' ? all : all.filter((r) => r.status === filter)

  const remove = async (rq: PersistedRfq, e: { stopPropagation: () => void }) => {
    e.stopPropagation()
    if (!window.confirm(`Delete draft “${rq.subject}”?`)) return
    setBusyId(rq.id)
    try { await deleteRfq(projectId, rq.id); await load() }
    catch { /* leave the row in place if the delete failed */ }
    finally { setBusyId(null) }
  }

  return (
    <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
      <div style={css('overflow-x:auto')}>
        <div style={css('display:flex;min-height:560px;min-width:720px')}>
          <div style={css('width:200px;flex:none;border-right:1px solid var(--border);padding:14px 10px;display:flex;flex-direction:column;gap:2px')}>
            {RFQ_FOLDERS.map((f) => (
              <Box key={f.key} onClick={() => setFilter(f.key)}
                style={css(`display:flex;align-items:center;justify-content:space-between;padding:8px 11px;border-radius:8px;font-size:13px;cursor:pointer;${filter === f.key ? 'background:var(--primary-softer);color:var(--primary);font-weight:600' : 'color:var(--text-2)'}`)}
                hover="background:var(--panel-2)">
                <span>{f.name}</span>
                <span style={css('font-size:11px;font-weight:600;color:var(--text-3)')}>{count(f.key)}</span>
              </Box>
            ))}
          </div>
          <div style={css('flex:1;min-width:0;display:flex;flex-direction:column')}>
            <div style={css('padding:13px 18px;border-bottom:1px solid var(--border)')}>
              <span style={css('font-size:14px;font-weight:600')}>{RFQ_FOLDERS.find((f) => f.key === filter)?.name}</span>
              <span style={css('font-size:14px;color:var(--text-3);font-weight:500')}> · {shown.length}</span>
            </div>
            <div style={css('flex:1;overflow-y:auto')}>
              {rfqs === null && <div style={css('padding:44px;text-align:center;font-size:13px;color:var(--text-3)')}>Loading…</div>}
              {rfqs !== null && shown.length === 0 && (
                <div style={css('padding:48px 24px;text-align:center')}>
                  <div style={css('font-size:13.5px;font-weight:600;color:var(--text-2);margin-bottom:4px')}>No RFQs here yet</div>
                  <div style={css('font-size:12.5px;color:var(--text-3)')}>Generate RFQs from the Suppliers tab — by buy-package or an ad-hoc search.</div>
                </div>
              )}
              {shown.map((rq) => (
                <Box key={rq.id} onClick={() => setOpen(rq)} style={css('display:flex;align-items:center;gap:12px;padding:13px 18px;border-bottom:1px solid var(--border);cursor:pointer')} hover="background:var(--panel-2)">
                  <div style={css(`width:34px;height:34px;border-radius:9px;background:${rq.logoBg || '#334155'};color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;flex:none`)}>{rq.logo}</div>
                  <div style={css('flex:1;min-width:0')}>
                    <div style={css('font-size:13.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{rq.subject}</div>
                    <div style={css('font-size:11.5px;color:var(--text-3);margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{rq.pkg || pkgLabel(rq.package)} · {(rq.recipients || []).length} recipient{(rq.recipients || []).length === 1 ? '' : 's'}</div>
                  </div>
                  <span style={DcBadge(rq.statusTone)}>{rq.status}</span>
                  {rq.status === 'Draft' && (
                    <Box as="button" onClick={(e: { stopPropagation: () => void }) => remove(rq, e)} disabled={busyId === rq.id}
                      style={css(`width:28px;height:28px;border-radius:7px;display:flex;align-items:center;justify-content:center;color:var(--text-3);flex:none;${busyId === rq.id ? 'opacity:.5' : ''}`)}
                      hover="background:var(--danger-soft);color:var(--danger)" title="Delete draft">
                      <Svg size={15} sw={1.9} d='M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m1 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6' />
                    </Box>
                  )}
                </Box>
              ))}
            </div>
          </div>
        </div>
      </div>
      {open && <RfqReviewModal projectId={projectId} rfq={open} onClose={() => { setOpen(null); load() }} />}
    </div>
  )
}

/* --------------------------------------------------------------- Quotes tab */
function TabQuotes({ m }: MProps) {
  const gridCols = 'minmax(200px,1.8fr) 120px 110px 116px 96px 110px'
  const projectId = m.activeProject.id
  const [ingesting, setIngesting] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  const checkReplies = async () => {
    setIngesting(true); setNote(null)
    try {
      await ingestQuotes(projectId)
      // Poll the background ingest until it finishes, then reload the model.
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 1500))
        const st = await getIngestStatus(projectId)
        if (st.status !== 'ingesting') {
          if (st.status === 'error') setNote(st.error || 'Ingest failed')
          else setNote(`${st.ingested} new quote${st.ingested === 1 ? '' : 's'}${st.mocked ? ' (simulated)' : ''}`)
          break
        }
      }
      await m.reload()
    } catch {
      setNote('Could not check for replies. Is the backend running?')
    } finally {
      setIngesting(false)
    }
  }

  // Quotes are separated by utility type (package); each group compares on its own.
  const groups: { pkg: string; rows: typeof m.quotes }[] = []
  for (const q of m.quotes) {
    let g = groups.find((x) => x.pkg === q.pkg)
    if (!g) { g = { pkg: q.pkg, rows: [] }; groups.push(g) }
    g.rows.push(q)
  }

  return (
    <>
      <div style={css('display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px')}>
        <h2 style={css('margin:0;font-size:15px;font-weight:600')}>Quotes received <span style={css('color:var(--text-3);font-weight:500')}>· {m.quotes.length} across {groups.length} {groups.length === 1 ? 'package' : 'packages'}</span></h2>
        <div style={css('display:flex;align-items:center;gap:10px;flex-wrap:wrap')}>
          {note && <span style={css('font-size:12px;color:var(--text-3)')}>{note}</span>}
          <Box as="button" onClick={ingesting ? undefined : checkReplies} style={css(`display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--panel);border:1px solid var(--border);color:var(--text);font-size:13px;font-weight:600;${ingesting ? 'opacity:.6' : ''}`)} hover="background:var(--panel-2)"><Svg size={15} sw={2} d='M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5' />{ingesting ? 'Checking…' : 'Check for replies'}</Box>
        </div>
      </div>
      {groups.length === 0 && (
        <div style={css('background:var(--panel);border:1px dashed var(--border-strong);border-radius:16px;padding:48px 24px;text-align:center')}>
          <div style={css('font-size:15px;font-weight:600;margin-bottom:6px')}>No quotes received yet</div>
          <div style={css('font-size:13px;color:var(--text-3)')}>Send RFQs to suppliers, then use “Check for replies” to pull in quotes.</div>
        </div>
      )}
      <div style={css('display:flex;flex-direction:column;gap:16px')}>
        {groups.map((g) => (
          <div key={g.pkg} style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
            <div style={css('display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:13px 16px;border-bottom:1px solid var(--border);background:var(--panel-2)')}>
              <div style={css('display:flex;align-items:center;gap:9px;min-width:0')}>
                <span style={css('font-size:13.5px;font-weight:700;letter-spacing:-.01em')}>{g.pkg}</span>
                <span style={css('font-size:11.5px;font-weight:600;color:var(--text-3);background:var(--panel-3);padding:2px 8px;border-radius:999px')}>{g.rows.length} {g.rows.length === 1 ? 'quote' : 'quotes'}</span>
              </div>
              <Box as="button" onClick={() => m.comparePackage(g.pkg)} style={css('display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border-radius:8px;background:var(--primary);color:#fff;font-size:12.5px;font-weight:600;white-space:nowrap')} hover="background:var(--primary-2)"><Svg size={14} d='M3 6h18M3 12h18M3 18h18' />Compare</Box>
            </div>
            <div style={css('overflow-x:auto')}><div style={css('min-width:640px')}>
              <div style={{ display: 'grid', gridTemplateColumns: gridCols, ...css('gap:10px;padding:9px 16px;border-bottom:1px solid var(--border);font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--text-3);text-transform:uppercase') }}><span>Supplier</span><span style={css('text-align:right')}>Quote</span><span style={css('text-align:right')}>Freight</span><span style={css('text-align:right')}>Total</span><span style={css('text-align:right')}>Lead</span><span style={css('text-align:right')}>Received</span></div>
              {g.rows.map((q, i) => (
                <Box key={i} onClick={q.onOpen} style={{ display: 'grid', gridTemplateColumns: gridCols, ...css('gap:10px;padding:13px 16px;border-bottom:1px solid var(--border);align-items:center;cursor:pointer') }} hover="background:var(--panel-2)">
                  <div style={css('display:flex;align-items:center;gap:10px;min-width:0')}><div style={q.logoStyle}>{q.logo}</div><span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{q.sup}</span>{q.best && <span style={css('display:inline-flex;align-items:center;gap:3px;font-size:10px;font-weight:700;color:var(--success);background:var(--success-soft);padding:2px 7px;border-radius:999px;white-space:nowrap')}><Svg size={10} sw={3} d='m5 12 5 5L20 7' />Best</span>}</div>
                  <span style={css("text-align:right;font-size:13px;font-family:'JetBrains Mono',monospace")}>{q.amount}</span>
                  <span style={css("text-align:right;font-size:13px;font-family:'JetBrains Mono',monospace;color:var(--text-2)")}>{q.freight}</span>
                  <span style={css("text-align:right;font-size:13.5px;font-weight:700;font-family:'JetBrains Mono',monospace")}>{q.total}</span>
                  <span style={css("text-align:right;font-size:12.5px;font-family:'JetBrains Mono',monospace")}>{q.lead}</span>
                  <span style={css('text-align:right;font-size:12px;color:var(--text-3)')}>{q.date}</span>
                </Box>
              ))}
            </div></div>
          </div>
        ))}
      </div>
    </>
  )
}

/* ------------------------------------------------------------- Compare tab */
const money = (v: number | null | undefined) => (v == null ? '—' : '$' + Math.round(v).toLocaleString())

// Live cost/lead/logistics for the current {line: supplierId} basket. Mirrors the
// backend's _cost_of so manual mix-and-match edits update instantly, while the
// award endpoint recomputes authoritatively on submit.
function summarizeAward(lc: LineComparison, sel: Record<string, string>) {
  const supById: Record<string, LineComparison['suppliers'][number]> = {}
  lc.suppliers.forEach((s) => { supById[s.id] = s })
  let material = 0, lead = 0
  const used = new Set<string>()
  for (const line of lc.lines) {
    const cell = line.cells.find((c) => c.supplierId === sel[line.name])
    if (cell && cell.extended != null) { material += cell.extended; used.add(cell.supplierId) }
    if (cell && cell.leadDays != null) lead = Math.max(lead, cell.leadDays)
  }
  let freight = 0, maxDist = 0
  used.forEach((sid) => {
    const s = supById[sid]
    if (!s) return
    freight += s.freight || 0
    if (s.distanceMiles != null) maxDist = Math.max(maxDist, s.distanceMiles)
  })
  const total = material + freight
  const single = lc.options.find((o) => o.key === 'single')
  return { material, freight, total, lead, deliveries: used.size, maxDist, savings: single ? single.total - total : 0 }
}

function TabCompare({ m }: MProps) {
  const [lc, setLc] = useState<LineComparison | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [sel, setSel] = useState<Record<string, string>>({})
  const [strategy, setStrategy] = useState<string>('mix')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true); setErr(null); setMsg(null)
    getLineComparison(m.projectId, m.comparePkg)
      .then((data) => {
        if (!alive) return
        setLc(data)
        const rec = data.options.find((o) => o.key === data.recommendedOption) || data.options[0]
        setSel(rec ? { ...rec.selections } : {})
        setStrategy(rec ? rec.key : 'custom')
      })
      .catch(() => { if (alive) setErr('Could not load comparison. Is the backend running?') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [m.projectId, m.comparePkg])

  const applyStrategy = (key: string) => {
    const opt = lc?.options.find((o) => o.key === key)
    if (opt) { setSel({ ...opt.selections }); setStrategy(key); setMsg(null) }
  }
  const pick = (line: string, supId: string) => {
    setSel((p) => ({ ...p, [line]: supId })); setStrategy('custom'); setMsg(null)
  }

  const back = (
    <Box as="button" onClick={m.closeCompare} style={css('display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:500;color:var(--text-2);margin-bottom:14px')} hover="color:var(--text)"><Svg size={16} d='m15 18-6-6 6-6' />Back to quotes</Box>
  )
  if (loading) return <>{back}<div style={css('padding:40px;text-align:center;color:var(--text-3);font-size:13px')}>Loading comparison…</div></>
  if (err || !lc) return <>{back}<div style={css('padding:40px;text-align:center;color:var(--text-3);font-size:13px')}>{err || 'No quotes to compare yet.'}</div></>

  const sum = summarizeAward(lc, sel)
  const gridCols = `minmax(150px,1.4fr) repeat(${lc.suppliers.length}, minmax(116px,1fr))`
  const submit = async () => {
    setBusy(true)
    try {
      const res = await awardPackage(m.projectId, lc.package, sel, strategy)
      setMsg(res.message)
      await m.reload()
    } catch {
      setMsg('Could not submit award. Is the backend running?')
    } finally { setBusy(false) }
  }
  const budgetPct = lc.budget ? Math.min(100, (sum.total / lc.budget) * 100) : null
  const overBudget = lc.budget != null && sum.total > lc.budget

  return (
    <>
      {back}
      <div style={css('margin-bottom:16px')}>
        <h2 style={css('margin:0;font-size:19px;font-weight:700;letter-spacing:-.02em')}>{lc.pkg} — Quote Comparison</h2>
        <p style={css('margin:4px 0 0;font-size:13px;color:var(--text-2)')}>{lc.suppliers.length} suppliers · {lc.lines.length} line items{lc.budget != null ? ` · budget ${money(lc.budget)}` : ''}</p>
      </div>

      {/* Strategy switcher */}
      <div style={css('display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px')}>
        {lc.options.map((o: AwardOption) => {
          const active = strategy === o.key
          return (
            <Box as="button" key={o.key} onClick={() => applyStrategy(o.key)}
              style={css(`flex:1;min-width:150px;text-align:left;padding:11px 13px;border-radius:12px;border:${active ? '2px solid var(--primary)' : '1px solid var(--border)'};background:${active ? 'var(--primary-softer)' : 'var(--panel)'}`)}
              hover={active ? '' : 'border-color:var(--border-strong)'}>
              <div style={css('display:flex;align-items:center;gap:6px;font-size:12.5px;font-weight:700')}>
                {o.key === 'mix' && <Svg size={14} fill d={SPARKLE} style={{ color: 'var(--primary)' }} />}{o.label}
              </div>
              <div style={css("font-size:15px;font-weight:700;margin-top:4px;font-family:'JetBrains Mono',monospace")}>{money(o.total)}</div>
              <div style={css('font-size:11px;color:var(--text-3);margin-top:2px')}>{o.leadDays != null ? `${o.leadDays}d lead · ` : ''}{o.suppliersUsed} {o.suppliersUsed === 1 ? 'supplier' : 'suppliers'}{o.savings > 0 ? ` · save ${money(o.savings)}` : ''}</div>
            </Box>
          )
        })}
        {strategy === 'custom' && (
          <div style={css('flex:1;min-width:150px;padding:11px 13px;border-radius:12px;border:2px solid var(--primary);background:var(--primary-softer)')}>
            <div style={css('font-size:12.5px;font-weight:700')}>Custom mix</div>
            <div style={css("font-size:15px;font-weight:700;margin-top:4px;font-family:'JetBrains Mono',monospace")}>{money(sum.total)}</div>
            <div style={css('font-size:11px;color:var(--text-3);margin-top:2px')}>your hand-picked award</div>
          </div>
        )}
      </div>

      <div style={css('display:grid;grid-template-columns:minmax(0,1.7fr) 320px;gap:16px;align-items:start')}>
        {/* Line-by-line grid */}
        <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
          <div style={css('overflow-x:auto')}><div style={css('min-width:560px')}>
            <div style={{ display: 'grid', gridTemplateColumns: gridCols, ...css('border-bottom:1px solid var(--border)') }}>
              <div style={css('padding:14px 16px;display:flex;align-items:flex-end;font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--text-3);text-transform:uppercase')}>Line item</div>
              {lc.suppliers.map((su) => (
                <div key={su.id} style={css('padding:12px 8px;display:flex;flex-direction:column;align-items:center;gap:5px;text-align:center;border-left:1px solid var(--border)')}>
                  <div style={lb(su.logoBg, 30)}>{su.logo}</div>
                  <div style={css('font-size:11.5px;font-weight:600;line-height:1.15')}>{su.name}</div>
                  <div style={css('font-size:10px;color:var(--text-3)')}>{su.leadDays != null ? `${su.leadDays}d` : '—'}{su.distanceMiles != null ? ` · ${Math.round(su.distanceMiles)}mi` : ''}</div>
                </div>
              ))}
            </div>
            {lc.lines.map((line) => (
              <div key={line.name} style={{ display: 'grid', gridTemplateColumns: gridCols, ...css('border-bottom:1px solid var(--border)') }}>
                <div style={css('padding:12px 16px;display:flex;flex-direction:column;justify-content:center;gap:2px')}>
                  <span style={css('font-size:12.5px;font-weight:600;line-height:1.25')}>{line.name}</span>
                  <span style={css('font-size:11px;color:var(--text-3)')}>{line.qty}</span>
                </div>
                {lc.suppliers.map((su) => {
                  const cell = line.cells.find((c) => c.supplierId === su.id)
                  const available = !!(cell && cell.available && cell.extended != null)
                  const selected = sel[line.name] === su.id
                  const best = !!(cell && cell.best)
                  return (
                    <Box as="button" key={su.id} onClick={available ? () => pick(line.name, su.id) : undefined}
                      style={{
                        borderLeft: '1px solid var(--border)',
                        ...css(`display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:10px 6px;cursor:${available ? 'pointer' : 'default'};position:relative;background:${selected ? 'var(--primary-softer)' : best ? 'var(--success-soft)' : 'transparent'};box-shadow:${selected ? 'inset 0 0 0 2px var(--primary)' : 'none'};opacity:${available ? 1 : 0.4}`),
                      }}
                      hover={available && !selected ? 'background:var(--panel-2)' : ''}>
                      {best && <span style={css('position:absolute;top:5px;right:6px;display:inline-flex;align-items:center;gap:2px;font-size:9px;font-weight:700;color:var(--success)')}><Svg size={10} sw={3} d='m5 12 5 5L20 7' />Best</span>}
                      <span style={css(`font-size:13.5px;font-weight:${selected || best ? 700 : 500};font-family:'JetBrains Mono',monospace;color:${best ? 'var(--success)' : 'var(--text)'}`)}>{available ? money(cell!.extended) : '—'}</span>
                      {available && <span style={css('font-size:10px;color:var(--text-3)')}>{cell!.unitPrice != null ? `$${cell!.unitPrice}/unit` : ''}{cell!.leadDays != null ? ` · ${cell!.leadDays}d` : ''}</span>}
                    </Box>
                  )
                })}
              </div>
            ))}
          </div></div>
        </div>

        {/* Award sidebar */}
        <div style={css('display:flex;flex-direction:column;gap:14px;position:sticky;top:72px')}>
          <div style={css('background:var(--primary-softer);border:1px solid var(--primary-soft);border-radius:16px;padding:18px;box-shadow:var(--shadow-md)')}>
            <div style={css('display:flex;align-items:center;gap:8px;margin-bottom:14px')}><span style={css('width:28px;height:28px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center')}><Svg size={16} fill d={SPARKLE} /></span><span style={css('font-size:13px;font-weight:700;color:var(--primary)')}>Award plan</span></div>
            <div style={css("font-size:11px;color:var(--text-3)")}>Total committed</div>
            <div style={css("font-size:24px;font-weight:700;font-family:'JetBrains Mono',monospace;line-height:1.1")}>{money(sum.total)}</div>
            {budgetPct != null && (
              <div style={css('margin-top:8px')}>
                <div style={css('height:6px;border-radius:999px;background:var(--panel-3);overflow:hidden')}><div style={{ width: `${budgetPct}%`, height: '100%', background: overBudget ? 'var(--danger)' : 'var(--success)' }} /></div>
                <div style={css(`font-size:11px;margin-top:3px;color:${overBudget ? 'var(--danger)' : 'var(--text-3)'}`)}>{overBudget ? `${money(sum.total - lc.budget!)} over` : `${money(lc.budget! - sum.total)} under`} budget</div>
              </div>
            )}
            <div style={css('display:flex;flex-direction:column;gap:7px;margin:14px 0;font-size:12.5px')}>
              <div style={css('display:flex;justify-content:space-between')}><span style={css('color:var(--text-2)')}>Materials</span><span style={css("font-family:'JetBrains Mono',monospace")}>{money(sum.material)}</span></div>
              <div style={css('display:flex;justify-content:space-between')}><span style={css('color:var(--text-2)')}>Freight ({sum.deliveries} {sum.deliveries === 1 ? 'delivery' : 'deliveries'})</span><span style={css("font-family:'JetBrains Mono',monospace")}>{money(sum.freight)}</span></div>
              <div style={css('display:flex;justify-content:space-between')}><span style={css('color:var(--text-2)')}>Lead time</span><span style={css("font-family:'JetBrains Mono',monospace")}>{sum.lead ? `${sum.lead} days` : '—'}</span></div>
              <div style={css('display:flex;justify-content:space-between')}><span style={css('color:var(--text-2)')}>Suppliers</span><span style={css("font-family:'JetBrains Mono',monospace")}>{sum.deliveries}</span></div>
              <div style={css('display:flex;justify-content:space-between')}><span style={css('color:var(--text-2)')}>Max haul</span><span style={css("font-family:'JetBrains Mono',monospace")}>{sum.maxDist ? `${Math.round(sum.maxDist)} mi` : '—'}</span></div>
            </div>
            {sum.savings > 0 && <div style={css('font-size:12px;color:var(--success);background:var(--success-soft);border-radius:9px;padding:9px 11px;margin-bottom:10px;line-height:1.4')}>Saves {money(sum.savings)} vs. the best single supplier.</div>}
            {msg && <div style={css('font-size:12px;color:var(--success);background:var(--success-soft);border-radius:9px;padding:9px 11px;margin-bottom:10px;line-height:1.4')}>{msg}</div>}
            <button onClick={busy ? undefined : submit} style={css(`width:100%;height:38px;border-radius:9px;background:var(--primary);color:#fff;font-size:13px;font-weight:600;${busy ? 'opacity:.6' : ''}`)}>{busy ? 'Submitting…' : `Submit award · issue ${sum.deliveries} ${sum.deliveries === 1 ? 'PO' : 'POs'}`}</button>
          </div>
        </div>
      </div>
    </>
  )
}

/* ------------------------------------------------------------- Timeline tab */
function TabTimeline({ m }: MProps) {
  // Completion is human-confirmed: check a milestone off (or undo it), then
  // reload so statuses (Complete / Overdue / active) recompute.
  const toggleDone = async (mm: { id?: number | null; done?: boolean }) => {
    if (mm.id == null) return
    try { await setTimelineEventDone(mm.id, !mm.done) } catch { /* reload shows truth either way */ }
    m.reload()
  }
  return (
    <>
      {m.gantt.length === 0 && m.milestones.length === 0 && (
      <div style={css('background:var(--panel);border:1px dashed var(--border-strong);border-radius:16px;padding:48px 24px;text-align:center;margin-bottom:16px')}>
        <div style={css('font-size:15px;font-weight:600;margin-bottom:6px')}>No timeline yet</div>
        <div style={css('font-size:13px;color:var(--text-3)')}>Upload project documents — construction schedules, contracts, or plans with phasing — and the milestones and schedule extracted from them will appear here.</div>
      </div>
      )}
      {m.gantt.length > 0 && (
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:18px;margin-bottom:16px')}>
        <h2 style={css('margin:0 0 16px;font-size:15px;font-weight:600')}>Procurement schedule</h2>
        <div style={css('overflow-x:auto')}><div style={css('min-width:620px')}>
          <div style={css('display:flex;margin-bottom:8px')}><div style={css('width:180px;flex:none')}></div><div style={css('flex:1;display:flex')}>{m.ganttCols.map((col, i) => <div key={i} style={css('flex:1;font-size:11px;font-weight:600;color:var(--text-3);text-align:center;border-left:1px solid var(--border)')}>{col}</div>)}</div></div>
          <div style={css('display:flex;flex-direction:column;gap:7px')}>
            {m.gantt.map((g, i) => (
              <div key={i} style={css('display:flex;align-items:center')}><div style={css('width:180px;flex:none;font-size:12.5px;font-weight:500;padding-right:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{g.name}</div><div style={css('flex:1;position:relative;height:30px;background:var(--panel-2);border-radius:7px')}><div style={g.barStyle}>{g.label}</div></div></div>
            ))}
          </div>
        </div></div>
      </div>
      )}
      {m.milestones.length > 0 && (
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:20px')}>
        <h2 style={css('margin:0 0 18px;font-size:15px;font-weight:600')}>Milestones</h2>
        <div style={css('display:flex;flex-direction:column')}>
          {m.milestones.map((mm, i) => (
            <div key={i} style={css('display:flex;gap:15px')}>
              <div style={css('display:flex;flex-direction:column;align-items:center;flex:none')}><span style={mm.dotStyle}></span><span style={css('flex:1;width:2px;background:var(--border);min-height:26px')}></span></div>
              <div style={css('flex:1;padding-bottom:18px;margin-top:-3px')}><div style={css('display:flex;align-items:center;gap:10px;flex-wrap:wrap')}><span style={css('font-size:13.5px;font-weight:600')}>{mm.name}</span><span style={mm.statusBadge}>{mm.status}</span>{mm.conflict && <span style={css('display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:var(--danger);background:var(--danger-soft);padding:3px 8px;border-radius:999px')}><Svg size={11} sw={2.2} d='M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z' />Date conflict</span>}<span style={css("font-size:12px;color:var(--text-3);font-family:'JetBrains Mono',monospace")}>{mm.date}</span>{mm.id != null && (
                  <Box as="button" onClick={() => toggleDone(mm)} style={css(`margin-left:auto;display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;padding:4px 10px;border-radius:7px;border:1px solid var(--border);${mm.done ? 'color:var(--text-3);background:var(--panel-2)' : 'color:var(--success);background:var(--success-soft)'}`)} hover="filter:brightness(.96)">{mm.done ? 'Undo' : <><Svg size={12} sw={2.6} d='M20 6 9 17l-5-5' />Mark done</>}</Box>
                )}</div><div style={css('font-size:12.5px;color:var(--text-2);margin-top:3px')}>{mm.desc}</div></div>
            </div>
          ))}
        </div>
      </div>
      )}
      <LendersPanel projectId={m.projectId} />
    </>
  )
}

/* --------------------------------------------------------- Lenders panel */
// The project's financing contacts. Groundwork for PRO-16: these are the
// recipients of the timeline-driven progress emails, so the panel lives on the
// Timeline tab next to the schedule the emails will report on.
function LendersPanel({ projectId }: { projectId: string }) {
  const [lenders, setLenders] = useState<Lender[]>([])
  const [name, setName] = useState('')
  const [institution, setInstitution] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const valid = name.trim().length > 0 && /\S+@\S+\.\S+/.test(email)

  useEffect(() => {
    let alive = true
    setLenders([])
    listLenders(projectId).then((l) => { if (alive) setLenders(l) }).catch(() => {})
    return () => { alive = false }
  }, [projectId])

  const add = async (e: FormEvent) => {
    e.preventDefault()
    if (!valid || busy) return
    setBusy(true); setErr(null)
    try {
      const lender = await createLender(projectId, { name, institution, email, phone })
      setLenders((ls) => [...ls, lender])
      setName(''); setInstitution(''); setEmail(''); setPhone('')
    } catch {
      setErr('Could not add lender — check the email address and try again.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number) => {
    try {
      await deleteLender(projectId, id)
      setLenders((ls) => ls.filter((l) => l.id !== id))
    } catch { /* row stays; nothing to clean up */ }
  }

  return (
    <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:20px;margin-top:16px')}>
      <h2 style={css('margin:0 0 4px;font-size:15px;font-weight:600')}>Lenders</h2>
      <div style={css('font-size:12.5px;color:var(--text-3);margin-bottom:16px')}>The project's financing contacts — they'll receive progress updates as the schedule advances.</div>
      <div style={css('display:flex;flex-direction:column;gap:8px;margin-bottom:16px')}>
        {lenders.map((l) => (
          <div key={l.id} style={css('display:flex;align-items:center;gap:12px;padding:10px 12px;border:1px solid var(--border);border-radius:11px;background:var(--panel-2)')}>
            <span style={css('width:32px;height:32px;border-radius:9px;background:var(--primary-soft);color:var(--primary);display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={16} sw={1.9} d='M3 21h18M4 9h16M12 3l8 4H4zM6 12v6M10 12v6M14 12v6M18 12v6' /></span>
            <div style={css('flex:1;min-width:0')}>
              <div style={css('font-size:13.5px;font-weight:600')}>{l.name}{l.institution && <span style={css('font-weight:400;color:var(--text-3)')}> · {l.institution}</span>}</div>
              <div style={css('font-size:12px;color:var(--text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{l.email}{l.phone && ` · ${l.phone}`}</div>
            </div>
            <Box as="button" onClick={() => remove(l.id)} title="Remove lender" style={css('width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--text-3);flex:none')} hover="background:var(--danger-soft);color:var(--danger)"><Svg size={15} sw={2} d='M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6.5 7l.8 12a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4l.8-12' /></Box>
          </div>
        ))}
        {lenders.length === 0 && (
          <div style={css('font-size:12.5px;color:var(--text-3);padding:6px 0')}>No lenders yet — add the financing contact below.</div>
        )}
      </div>
      <form onSubmit={add} style={css('display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end')}>
        <div style={css('flex:1.2;min-width:150px')}>
          <label style={fieldLabel}>Contact name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sarah Chen" style={fieldInput} />
        </div>
        <div style={css('flex:1.2;min-width:150px')}>
          <label style={fieldLabel}>Institution</label>
          <input value={institution} onChange={(e) => setInstitution(e.target.value)} placeholder="e.g. First National Bank" style={fieldInput} />
        </div>
        <div style={css('flex:1.4;min-width:180px')}>
          <label style={fieldLabel}>Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@bank.com" style={fieldInput} />
        </div>
        <div style={css('flex:1;min-width:120px')}>
          <label style={fieldLabel}>Phone <span style={css('font-weight:400;color:var(--text-3)')}>(optional)</span></label>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(555) 000-0000" style={fieldInput} />
        </div>
        <Box as="button" type="submit" style={{ ...css('display:inline-flex;align-items:center;gap:7px;height:38px;padding:0 14px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13px;font-weight:600;box-shadow:var(--shadow-sm);flex:none'), opacity: valid && !busy ? 1 : 0.5, pointerEvents: valid && !busy ? 'auto' : 'none' }} hover="background:var(--primary-2)"><Svg size={15} sw={2.2} d={PLUS} />Add lender</Box>
      </form>
      {err && <div style={css('font-size:12.5px;color:var(--danger);margin-top:10px')}>{err}</div>}
    </div>
  )
}

/* ------------------------------------------------------- Supplier drawer */
function SupplierDrawer({ m }: MProps) {
  const a = m.activeSupplier
  return (
    <div style={css('position:fixed;inset:0;z-index:60;display:flex;justify-content:flex-end')}>
      <div onClick={m.closeSupplier} style={css('position:absolute;inset:0;background:rgba(15,20,30,.4)')}></div>
      <div style={css('position:relative;width:min(440px,100%);height:100%;background:var(--panel);box-shadow:var(--shadow-lg);display:flex;flex-direction:column;animation:pcUp .2s ease both;overflow-y:auto')}>
        <div style={css('display:flex;align-items:flex-start;gap:13px;padding:20px;border-bottom:1px solid var(--border)')}>
          <div style={a.logoStyle}>{a.logo}</div>
          <div style={css('flex:1;min-width:0')}><div style={css('font-size:16px;font-weight:700')}>{a.name}</div><div style={css('font-size:12.5px;color:var(--text-3);margin-top:1px')}>{a.contact} · Account rep</div><div style={css('margin-top:7px')}><span style={a.rfqBadge}>{a.rfq}</span></div></div>
          <Box as="button" onClick={m.closeSupplier} style={css('width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--text-2)')} hover="background:var(--panel-2)"><Svg size={18} d='M6 6l12 12M18 6 6 18' /></Box>
        </div>
        <div style={css('padding:20px;display:flex;flex-direction:column;gap:22px')}>
          <div>
            <div style={css('font-size:11px;font-weight:700;letter-spacing:.06em;color:var(--text-3);text-transform:uppercase;margin-bottom:11px')}>Contact information</div>
            <div style={css('display:flex;flex-direction:column;gap:10px')}>
              <div style={css('display:flex;align-items:center;gap:11px;font-size:13px')}><Svg size={16} sw={1.9} stroke="var(--text-3)" d='M5 4h3l2 5-2.5 1.5a11 11 0 0 0 5 5L14 13l5 2v3a2 2 0 0 1-2 2A15 15 0 0 1 3 6a2 2 0 0 1 2-2z' />{a.phone}</div>
              <div style={css('display:flex;align-items:center;gap:11px;font-size:13px')}><Svg size={16} sw={1.9} stroke="var(--text-3)" d='<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 7 8.5 5.5L20.5 7"/>' />{a.email}</div>
              <div style={css('display:flex;align-items:center;gap:11px;font-size:13px')}><Svg size={16} sw={1.9} stroke="var(--text-3)" d='<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z"/>' />{a.web}</div>
            </div>
          </div>
          <div style={css('display:flex;gap:10px')}>
            <div style={css('flex:1;background:var(--panel-2);border:1px solid var(--border);border-radius:12px;padding:12px')}><div style={css('font-size:11px;color:var(--text-3)')}>Quotes</div><div style={css("font-size:18px;font-weight:700;font-family:'JetBrains Mono',monospace")}>{a.fin.submitted}</div></div>
            <div style={css('flex:1.4;background:var(--panel-2);border:1px solid var(--border);border-radius:12px;padding:12px')}><div style={css('font-size:11px;color:var(--text-3)')}>Total value</div><div style={css("font-size:18px;font-weight:700;font-family:'JetBrains Mono',monospace")}>{a.fin.total}</div></div>
            <div style={css('flex:1.1;background:var(--panel-2);border:1px solid var(--border);border-radius:12px;padding:12px')}><div style={css('font-size:11px;color:var(--text-3)')}>Avg lead</div><div style={css("font-size:18px;font-weight:700;font-family:'JetBrains Mono',monospace")}>{a.fin.avg}</div></div>
          </div>
          <div>
            <div style={css('font-size:11px;font-weight:700;letter-spacing:.06em;color:var(--text-3);text-transform:uppercase;margin-bottom:13px')}>Communication history</div>
            <div style={css('display:flex;flex-direction:column')}>
              {m.supComms.map((c, i) => (
                <div key={i} style={css('display:flex;gap:12px')}>
                  <div style={css('display:flex;flex-direction:column;align-items:center;flex:none')}><div style={c.chipStyle}><IconHtml html={c.iconHtml} size={14} /></div><span style={css('flex:1;width:2px;background:var(--border);min-height:14px')}></span></div>
                  <div style={css('flex:1;padding-bottom:16px')}><div style={css('font-size:13px;font-weight:600')}>{c.title}</div><div style={css('font-size:12px;color:var(--text-2);margin-top:2px;line-height:1.45')}>{c.body}</div><div style={css('font-size:11px;color:var(--text-3);margin-top:4px')}>{c.time}</div></div>
                </div>
              ))}
              {m.supComms.length === 0 && (
                <div style={css('font-size:12.5px;color:var(--text-3)')}>No communication yet.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ----------------------------------------------------------- Mobile nav */
function MobileNav({ m }: MProps) {
  return (
    <div style={css('position:fixed;inset:0;z-index:70;display:flex')}>
      <div onClick={m.closeMnav} style={css('position:absolute;inset:0;background:rgba(15,20,30,.45)')}></div>
      <aside style={css('position:relative;width:262px;height:100%;background:var(--panel);box-shadow:var(--shadow-lg);padding:16px 12px;display:flex;flex-direction:column;animation:pcUp .2s ease both')}>
        <div style={css('display:flex;align-items:center;gap:10px;padding:6px 8px 18px')}>
          <div style={css('width:30px;height:30px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center')}><Svg size={17} sw={2.2} d='M3 7l9-4 9 4-9 4-9-4z" /><path d="M3 12l9 4 9-4" /><path d="M3 17l9 4 9-4' /></div>
          <span style={css('font-size:15px;font-weight:700')}>ProcureAI</span>
        </div>
        <Box as="button" onClick={m.goDashboard} style={m.navStyle.dashboard} hover="background:var(--panel-2)"><Svg sw={1.9} d='<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>' /><span style={css('flex:1;text-align:left')}>Dashboard</span></Box>
        <Box as="button" onClick={m.goProjects} style={m.navStyle.projects} hover="background:var(--panel-2)"><Svg sw={1.9} d='M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z' /><span style={css('flex:1;text-align:left')}>Projects</span></Box>
        <Box as="button" onClick={m.goSuppliers} style={m.navStyle.suppliers} hover="background:var(--panel-2)"><Svg sw={1.9} d='<rect x="5" y="3" width="14" height="18" rx="1.6"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M10 21v-3h4v3"/>' /><span style={css('flex:1;text-align:left')}>Suppliers</span></Box>
        <Box as="button" onClick={m.goSettings} style={m.navStyle.settings} hover="background:var(--panel-2)"><Svg sw={1.9} d='<circle cx="12" cy="12" r="3"/>' /><span style={css('flex:1;text-align:left')}>Settings</span></Box>
        <div style={{ flex: 1 }}></div>
        <Box as="button" onClick={m.goDS} style={m.navStyle.ds} hover="background:var(--panel-2)"><Svg sw={1.9} d='<circle cx="13.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="13" r="2.5"/><circle cx="8.5" cy="7.5" r="2.5"/><circle cx="6.5" cy="14.5" r="2.5"/><path d="M12 22a5 5 0 0 1-3-9"/>' /><span style={css('flex:1;text-align:left')}>Design System</span></Box>
      </aside>
    </div>
  )
}

/* ----------------------------------------------------- New project modal */
const fieldLabel = css('display:block;font-size:12.5px;font-weight:600;color:var(--text-2);margin-bottom:6px')
const fieldInput = css('width:100%;height:38px;padding:0 12px;border-radius:9px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:13.5px')

function NewProjectModal({ m }: MProps) {
  const [name, setName] = useState('')
  const [loc, setLoc] = useState('')
  const [value, setValue] = useState('')
  const valid = name.trim().length > 0

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!valid) return
    m.createProject({ name, loc, value })
  }

  return (
    <div style={css('position:fixed;inset:0;z-index:80;display:flex;align-items:center;justify-content:center;padding:20px')}>
      <div onClick={m.closeNewProject} style={css('position:absolute;inset:0;background:rgba(15,20,30,.45)')}></div>
      <form onSubmit={submit} style={css('position:relative;width:min(460px,100%);background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-lg);animation:pcUp .2s ease both;overflow:hidden')}>
        <div style={css('display:flex;align-items:flex-start;gap:12px;padding:20px 20px 16px;border-bottom:1px solid var(--border)')}>
          <span style={css('width:34px;height:34px;border-radius:9px;background:var(--primary-soft);color:var(--primary);display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={18} sw={2.2} d={PLUS} /></span>
          <div style={css('flex:1;min-width:0')}>
            <div style={css('font-size:16px;font-weight:700;letter-spacing:-.01em')}>New project</div>
            <div style={css('font-size:12.5px;color:var(--text-3);margin-top:1px')}>Everything in ProcureAI lives inside a project</div>
          </div>
          <Box as="button" type="button" onClick={m.closeNewProject} style={css('width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--text-2)')} hover="background:var(--panel-2)"><Svg size={18} d='M6 6l12 12M18 6 6 18' /></Box>
        </div>
        <div style={css('padding:20px;display:flex;flex-direction:column;gap:16px')}>
          <div>
            <label style={fieldLabel}>Project name</label>
            <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Riverside Water Treatment Plant" style={fieldInput} />
          </div>
          <div style={css('display:flex;gap:12px')}>
            <div style={{ flex: 1.4 }}>
              <label style={fieldLabel}>Location</label>
              <input value={loc} onChange={(e) => setLoc(e.target.value)} placeholder="City, ST" style={fieldInput} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={fieldLabel}>Est. value</label>
              <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="$0" style={fieldInput} />
            </div>
          </div>
        </div>
        <div style={css('display:flex;justify-content:flex-end;gap:9px;padding:0 20px 20px')}>
          <Box as="button" type="button" onClick={m.closeNewProject} style={css('height:36px;padding:0 14px;border-radius:9px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:13px;font-weight:600')} hover="background:var(--panel-2)">Cancel</Box>
          <Box as="button" type="submit" style={{ ...css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13px;font-weight:600;box-shadow:var(--shadow-sm)'), opacity: valid ? 1 : 0.5, pointerEvents: valid ? 'auto' : 'none' }} hover="background:var(--primary-2)"><Svg size={15} sw={2.2} d={PLUS} />Create project</Box>
        </div>
      </form>
    </div>
  )
}
