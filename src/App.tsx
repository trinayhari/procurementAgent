import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, DragEvent, FormEvent } from 'react'
import { Box, DcIcon, css } from './lib'
import { buildModel } from './model'
import type { Model, State } from './model'
import {
  loadModelData, getPlanTypes, uploadDocument, getDocumentLineItems,
  saveDocumentLineItems, confirmDocument,
  searchSuppliers, getFoundSuppliers, generateRfq, listGeneratedRfqs, saveRfq, sendRfq,
} from './api'
import type { SupplierSearchResult, FoundSupplier, PersistedRfq, RfqRecipient } from './api'

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
const CHEVRON = 'm9 6 6 6-6 6'
const PIN = 'M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z" /><circle cx="12" cy="10" r="2.6'

export default function App() {
  const [s, setS] = useState<State>({
    nav: 'dashboard', tab: 'overview', compare: false, docIdx: 0, rfqIdx: 0,
    supplierId: null, theme: 'light', vw: typeof window !== 'undefined' ? window.innerWidth : 1280, mnav: false,
    data: null,
    planTypes: null, planType: 'site_plan', uploading: false, uploadError: null, docLineItems: null,
    editBom: false, bomDraft: null, bomBusy: false,
  })
  const set = (patch: Partial<State>) => setS((prev) => ({ ...prev, ...patch }))

  useEffect(() => {
    const f = () => set({ vw: window.innerWidth })
    window.addEventListener('resize', f)
    return () => window.removeEventListener('resize', f)
  }, [])

  // Hydrate the backend bundle for one project; on failure the model falls back
  // to its literals. Pass an explicit id (e.g. right after creating a project) to
  // avoid the stale-closure value of s.projectId.
  const reload = (pid = s.projectId) =>
    loadModelData(pid || 'riverside').then((data) => set({ data })).catch(() => {})
  useEffect(() => { reload() }, [])

  // Refetch the workspace bundle whenever the open project changes, so each
  // project shows its own documents/quotes/etc. instead of the last one's.
  useEffect(() => { if (s.projectId) reload(s.projectId) }, [s.projectId])

  // Plan types the extractor supports (drives the upload selector).
  useEffect(() => {
    getPlanTypes().then((planTypes) => set({ planTypes })).catch(() => {})
  }, [])

  // Upload a plan set, then refresh so it appears in the documents list.
  const uploadDoc = async (file: File) => {
    set({ uploading: true, uploadError: null })
    try {
      await uploadDocument(file, s.planType, s.projectId)
      set({ docIdx: 0 }) // newest doc lands at the top
      await reload()
    } catch (e) {
      set({ uploadError: 'Upload failed. Is the backend running?' })
    } finally {
      set({ uploading: false })
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
    planTypes: s.planTypes, planType: s.planType,
    uploading: s.uploading, uploadError: s.uploadError,
    docLineItems: s.docLineItems, onUpload: uploadDoc,
    editBom: s.editBom, bomDraft: s.bomDraft, bomBusy: s.bomBusy,
    startBomEdit, cancelBomEdit, editBomItem, addBomItem, deleteBomItem, saveBom, confirmBom,
  })

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

      {m.supplierOpen && <SupplierDrawer m={m} />}
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
      <div style={css('margin-top:18px;padding:0 8px 8px;font-size:10.5px;font-weight:700;letter-spacing:.08em;color:var(--text-3)')}>SAVED VIEWS</div>
      <div style={css('display:flex;flex-direction:column;gap:2px')}>
        <Box as="button" onClick={m.openProject} style={css('display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:8px;font-size:13px;color:var(--text-2)')} hover="background:var(--panel-2)">
          <span style={css('width:7px;height:7px;border-radius:2px;background:var(--primary);flex:none')}></span>
          <span style={css('flex:1;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>Riverside WTP</span>
        </Box>
        <Box as="button" onClick={m.openProject} style={css('display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:8px;font-size:13px;color:var(--text-2)')} hover="background:var(--panel-2)">
          <span style={css('width:7px;height:7px;border-radius:2px;background:var(--violet);flex:none')}></span>
          <span style={css('flex:1;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>Eastgate Mixed-Use</span>
        </Box>
      </div>
      <div style={{ flex: 1 }}></div>
      <Box as="button" onClick={m.goDS} style={m.navStyle.ds} hover="background:var(--panel-2)">
        <Svg sw={1.9} d='<circle cx="13.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="13" r="2.5"/><circle cx="8.5" cy="7.5" r="2.5"/><circle cx="6.5" cy="14.5" r="2.5"/><path d="M12 22a5 5 0 0 1-3-9"/>' />
        <span style={css('flex:1;text-align:left')}>Design System</span>
      </Box>
      <div style={css('display:flex;align-items:center;gap:10px;margin-top:8px;padding:9px 8px;border-top:1px solid var(--border)')}>
        <div style={css('width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#7c3aed);color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex:none')}>JM</div>
        <div style={css('display:flex;flex-direction:column;line-height:1.2;min-width:0;flex:1')}>
          <span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>Jordan Mills</span>
          <span style={css('font-size:11px;color:var(--text-3)')}>Meridian Civil Co.</span>
        </div>
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
          <h1 style={css('margin:0;font-size:clamp(22px,3vw,27px);font-weight:700;letter-spacing:-.02em')}>Good afternoon, Jordan</h1>
          <p style={css('margin:5px 0 0;font-size:14px;color:var(--text-2)')}>Portfolio snapshot across 5 active projects · Tuesday, Jun 17</p>
        </div>
        <Box as="button" onClick={m.openNewProject} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13.5px;font-weight:600;box-shadow:var(--shadow-sm)')} hover="background:var(--primary-2)">
          <Svg size={16} sw={2.2} d={PLUS} />New project
        </Box>
      </div>

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
      <div style={css('display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:15px')}>
        {m.projects.map((p, i) => (
          <Box as="button" key={i} onClick={() => m.openProject(p)} style={css('text-align:left;background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:18px;box-shadow:var(--shadow-sm);display:flex;flex-direction:column;gap:14px;transition:box-shadow .15s,transform .15s,border-color .15s')} hover="box-shadow:var(--shadow-md);transform:translateY(-2px);border-color:var(--border-strong)">
            <div style={css('display:flex;align-items:flex-start;justify-content:space-between;gap:10px')}>
              <div style={css('min-width:0')}>
                <div style={css('font-size:15.5px;font-weight:600;letter-spacing:-.01em;line-height:1.25')}>{p.name}</div>
                <div style={css('display:flex;align-items:center;gap:5px;font-size:12.5px;color:var(--text-3);margin-top:3px')}><Svg size={13} d={PIN} />{p.loc}</div>
              </div>
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
  return (
    <div style={css('animation:pcUp .25s ease both')}>
      <div style={css('display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:20px')}>
        <div>
          <h1 style={css('margin:0;font-size:clamp(22px,3vw,27px);font-weight:700;letter-spacing:-.02em')}>Suppliers</h1>
          <p style={css('margin:5px 0 0;font-size:14px;color:var(--text-2)')}>Your network across all projects · 6 shown</p>
        </div>
        <Box as="button" style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13.5px;font-weight:600;box-shadow:var(--shadow-sm)')} hover="background:var(--primary-2)">
          <Svg size={16} sw={2.2} d={PLUS} />Add supplier
        </Box>
      </div>
      <div style={css('display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px')}>
        {m.suppliers.map((x, i) => <SupplierCard key={i} x={x} />)}
      </div>
    </div>
  )
}

/* ----------------------------------------------------------------- Settings */
function Settings({ m }: MProps) {
  const toggleOn = css('width:38px;height:22px;border-radius:999px;background:var(--primary);position:relative;flex:none')
  return (
    <div style={css('animation:pcUp .25s ease both;max-width:680px')}>
      <h1 style={css('margin:0 0 4px;font-size:clamp(22px,3vw,27px);font-weight:700;letter-spacing:-.02em')}>Settings</h1>
      <p style={css('margin:0 0 22px;font-size:14px;color:var(--text-2)')}>Manage your workspace and procurement defaults</p>
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
        <div style={css('display:flex;align-items:center;gap:14px;padding:18px;border-bottom:1px solid var(--border)')}>
          <div style={css('width:46px;height:46px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#7c3aed);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600')}>JM</div>
          <div style={{ flex: 1 }}><div style={css('font-size:15px;font-weight:600')}>Jordan Mills</div><div style={css('font-size:12.5px;color:var(--text-3)')}>jordan@meridiancivil.com</div></div>
          <Box as="button" style={css('height:34px;padding:0 13px;border-radius:8px;border:1px solid var(--border);font-size:12.5px;font-weight:600')} hover="background:var(--panel-2)">Edit profile</Box>
        </div>
        <div style={css('padding:8px 0')}>
          <div style={css('display:flex;align-items:center;justify-content:space-between;padding:14px 18px')}>
            <div><div style={css('font-size:13.5px;font-weight:600')}>Appearance</div><div style={css('font-size:12px;color:var(--text-3)')}>Theme used across the workspace</div></div>
            <Box as="button" onClick={m.toggleTheme} style={css('height:32px;padding:0 13px;border-radius:8px;border:1px solid var(--border);font-size:12.5px;font-weight:600;display:flex;align-items:center;gap:6px')} hover="background:var(--panel-2)">{m.isDark ? 'Dark' : 'Light'}</Box>
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
            <div style={css('display:flex;align-items:baseline;gap:12px')}><span style={css("font-size:15px;font-weight:600;font-family:'JetBrains Mono',monospace")}>$495,600</span><span style={css("font-size:11px;color:var(--text-3);font-family:'JetBrains Mono',monospace")}>Mono · data</span></div>
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
            <span style={css('display:flex;align-items:center;gap:5px')}><Svg size={14} d={PIN} />{m.activeProject.loc}</span>
            <span>Value <strong style={css("color:var(--text);font-family:'JetBrains Mono',monospace")}>{m.activeProject.value}</strong></span>
            <span>Bid date <strong style={css('color:var(--text)')}>Jun 20, 2026</strong></span>
          </div>
        </div>
        <div style={css('display:flex;gap:9px;flex-wrap:wrap')}>
          <Box as="button" onClick={m.setDocuments} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 13px;border-radius:9px;background:var(--panel);border:1px solid var(--border);color:var(--text);font-size:13px;font-weight:600')} hover="background:var(--panel-2)"><Svg size={15} d='M12 16V4M7 9l5-5 5 5" /><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2' />Upload</Box>
          <Box as="button" onClick={m.setSuppliers} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 13px;border-radius:9px;background:var(--panel);border:1px solid var(--border);color:var(--text);font-size:13px;font-weight:600')} hover="background:var(--panel-2)"><Svg size={15} sw={2.2} d={PLUS} />Add Supplier</Box>
          <Box as="button" onClick={m.setRfqs} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:var(--on-primary);font-size:13px;font-weight:600;box-shadow:var(--shadow-sm)')} hover="background:var(--primary-2)"><Svg size={15} fill d={SPARKLE_SM} />Generate RFQs</Box>
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
  return (
    <>
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
      <div style={css('display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:16px;align-items:start;margin-bottom:16px')}>
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
        <div style={css('background:var(--primary-softer);border:1px solid var(--primary-soft);border-radius:16px;padding:18px;box-shadow:var(--shadow-sm)')}>
          <div style={css('display:flex;align-items:center;gap:8px;margin-bottom:11px')}><span style={css('width:26px;height:26px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center')}><Svg size={15} fill d={SPARKLE} /></span><span style={css('font-size:13px;font-weight:700;color:var(--primary)')}>ProcureAI suggests</span></div>
          <p style={css('margin:0 0 14px;font-size:13.5px;line-height:1.5;color:var(--text)')}>The <strong>Water Utilities</strong> package has 3 competitive quotes in. Ferguson offers the best balance of price and a 14-day lead — <strong>$184K below budget</strong>. Ready to compare.</p>
          <Box as="button" onClick={m.setQuotes} style={css('display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 13px;border-radius:8px;background:var(--primary);color:#fff;font-size:13px;font-weight:600')} hover="background:var(--primary-2)">Review water quotes<Svg size={15} sw={2.2} d={CHEVRON} /></Box>
        </div>
      </div>
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
        <div style={css('padding:15px 18px;border-bottom:1px solid var(--border)')}><h2 style={css('margin:0;font-size:15px;font-weight:600')}>Recent project activity</h2></div>
        <div style={css('padding:6px 8px')}>
          {m.activity.map((a, i) => (
            <Box key={i} style={css('display:flex;gap:11px;padding:10px;border-radius:10px')} hover="background:var(--panel-2)">
              <div style={a.chipStyle}><IconHtml html={a.iconHtml} /></div>
              <div style={css('flex:1;min-width:0')}><div style={css('font-size:13px;font-weight:500')}>{a.title}</div><div style={css('font-size:11.5px;color:var(--text-3);margin-top:1px')}>{a.meta}</div></div>
              <span style={css('font-size:11px;color:var(--text-3);white-space:nowrap')}>{a.time}</span>
            </Box>
          ))}
        </div>
      </div>
    </>
  )
}

/* ----------------------------------------------------------- Documents tab */
function Dropzone({ m }: MProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)

  const onFiles = (fileList: FileList | null) => {
    const file = fileList && fileList[0]
    if (file) m.onUpload(file)
  }
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault(); setDrag(false)
    if (!m.uploading) onFiles(e.dataTransfer.files)
  }
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={onDrop}
      style={css(`border:1.5px dashed ${drag ? 'var(--primary)' : 'var(--border-strong)'};border-radius:14px;padding:22px;display:flex;align-items:center;gap:16px;background:${drag ? 'var(--primary-softer)' : 'var(--panel)'};margin-bottom:18px;transition:background .12s,border-color .12s`)}
    >
      <input
        ref={inputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" style={{ display: 'none' }}
        onChange={(e) => { onFiles(e.target.files); e.target.value = '' }}
      />
      <div style={css('width:44px;height:44px;border-radius:11px;background:var(--primary-soft);color:var(--primary);display:flex;align-items:center;justify-content:center;flex:none')}>
        {m.uploading
          ? <span style={css('width:18px;height:18px;border:2px solid var(--primary);border-top-color:transparent;border-radius:50%;display:inline-block;animation:pcSpin .7s linear infinite')}></span>
          : <Svg size={21} d='M12 16V4M7 9l5-5 5 5" /><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2' />}
      </div>
      <div style={css('flex:1;min-width:0')}>
        <div style={css('font-size:14px;font-weight:600')}>{m.uploading ? 'Uploading & extracting…' : 'Drag & drop plans for AI extraction'}</div>
        <div style={css('font-size:12.5px;color:var(--text-3);margin-top:2px')}>
          {m.uploadError
            ? <span style={css('color:var(--danger)')}>{m.uploadError}</span>
            : 'PDF or image · GPT-4.1 vision extracts a Bill of Materials per discipline'}
        </div>
      </div>
      <select
        value={m.planType} onChange={(e) => m.setPlanType(e.target.value)}
        style={css('height:36px;padding:0 10px;border-radius:9px;background:var(--panel-2);border:1px solid var(--border);color:var(--text);font-size:12.5px;font-weight:600;flex:none;cursor:pointer')}
      >
        {(m.planTypes || []).map((t) => (
          <option key={t.key} value={t.key} disabled={!t.enabled}>
            {t.label}{t.enabled ? '' : ' (coming soon)'}
          </option>
        ))}
      </select>
      <Box
        as="button" onClick={() => inputRef.current && inputRef.current.click()} disabled={m.uploading}
        style={css(`height:36px;padding:0 15px;border-radius:9px;background:var(--primary);color:#fff;font-size:13px;font-weight:600;flex:none;opacity:${m.uploading ? '.6' : '1'}`)}
        hover="background:var(--primary-2)"
      >Browse files</Box>
    </div>
  )
}

function TabDocuments({ m }: MProps) {
  return (
    <>
      <Dropzone m={m} />
      <div style={css('display:grid;grid-template-columns:minmax(0,1.7fr) 330px;gap:16px;align-items:start')}>
        <div style={css('display:flex;flex-direction:column;gap:16px;min-width:0')}>
          <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
            <div style={css('display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border)')}><h2 style={css('margin:0;font-size:14.5px;font-weight:600')}>Project documents</h2><span style={css('font-size:12px;color:var(--text-3)')}>{m.docs.length} files</span></div>
            <div style={css('display:grid;grid-template-columns:minmax(150px,2fr) 124px 116px 104px;gap:10px;padding:9px 16px;border-bottom:1px solid var(--border);font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--text-3);text-transform:uppercase')}><span>File</span><span>Type</span><span>Uploaded</span><span>AI Status</span></div>
            {m.docs.map((d, i) => (
              <div key={i} onClick={d.onOpen} style={d.rowStyle}>
                <div style={css('display:flex;align-items:center;gap:10px;min-width:0')}><span style={css('width:30px;height:30px;border-radius:7px;background:var(--panel-3);color:var(--text-2);display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={15} sw={1.8} d='M14 3v5h5" /><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z' /></span><span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{d.name}</span></div>
                <span style={css('font-size:12px;color:var(--text-2)')}>{d.type}</span>
                <span style={css('font-size:12px;color:var(--text-2)')}>{d.date}</span>
                <span><span style={d.statusBadge}>{d.processing && <span style={css('width:9px;height:9px;border:1.5px solid var(--primary);border-top-color:transparent;border-radius:50%;display:inline-block;animation:pcSpin .7s linear infinite')}></span>}{d.status}</span></span>
              </div>
            ))}
          </div>
          <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
            <div style={css('display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border)')}>
              <div style={css('display:flex;align-items:center;gap:9px;min-width:0')}><span style={css('font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{m.doc.name}</span><span style={css('font-size:12px;color:var(--text-3);white-space:nowrap')}>{m.doc.pages} pages</span></div>
              <span style={css('display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;color:var(--primary);background:var(--primary-soft);padding:3px 9px;border-radius:999px')}><Svg size={12} fill d={SPARKLE_SM} />AI Analysis</span>
            </div>
            <div style={css('position:relative;height:280px;background:repeating-linear-gradient(45deg,var(--panel-2),var(--panel-2) 12px,var(--panel-3) 12px,var(--panel-3) 24px);display:flex;align-items:center;justify-content:center')}>
              <span style={css("font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-3);background:var(--panel);padding:6px 12px;border-radius:8px;border:1px solid var(--border)")}>plan_sheet_preview.pdf</span>
              <div style={css('position:absolute;left:18px;bottom:18px;display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--border);box-shadow:var(--shadow-md);padding:8px 12px;border-radius:10px')}><span style={css('width:24px;height:24px;border-radius:6px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center')}><Svg size={13} fill d={SPARKLE_SM} /></span><span style={css('font-size:12.5px;font-weight:600')}>AI detected <span style={css('color:var(--primary)')}>{m.doc.items}</span> line items</span></div>
            </div>
          </div>
        </div>
        <ExtractedPanel m={m} />
      </div>
    </>
  )
}

/* ------------------------------- AI-extracted materials (human-in-the-loop) */
function ExtractedPanel({ m }: MProps) {
  const editing = m.bomEditing
  // In edit mode we render the draft (plain BOM groups); otherwise the extracted
  // groups, which carry presentational extras (dotStyle/countBadge).
  const groups = (editing ? m.bomDraft : m.extracted) as BomGroup[]
  const reviewed = m.doc && m.doc.reviewed
  const inputCss = css('flex:1;min-width:0;font-size:12px;padding:5px 7px;border-radius:6px;border:1px solid var(--border);background:var(--panel-2);color:var(--text)')

  return (
    <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);position:sticky;top:72px;overflow:hidden')}>
      <div style={css('padding:14px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px')}>
        <span style={css('width:24px;height:24px;border-radius:7px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={14} fill d={SPARKLE_SM} /></span>
        <h2 style={css('margin:0;font-size:14px;font-weight:600;flex:1')}>{editing ? 'Edit materials' : 'Extracted materials'}</h2>
        {!editing && reviewed && (
          <span style={css('display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:var(--success);background:var(--success-soft);padding:3px 8px;border-radius:999px')}><Svg size={12} sw={2.4} d="M20 6 9 17l-5-5" />Confirmed</span>
        )}
        {!editing && !reviewed && (
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
// Buy-packages the BOM is grouped into (mirrors the backend sourcing.packages).
const BUY_PACKAGES = [
  { key: 'water', label: 'Water Utilities' },
  { key: 'sewer', label: 'Sanitary Sewer' },
  { key: 'storm', label: 'Storm Drain' },
  { key: 'erosion', label: 'Erosion Control' },
]

const TIER_TONE: Record<number, string> = { 1: 'success', 2: 'blue', 3: 'violet' }

function pkgLabel(key: string): string {
  const p = BUY_PACKAGES.find((x) => x.key === key)
  return p ? p.label : key
}

// Self-contained supplier search: pick a package, set a radius, search Google
// Places (mock when no key), review tiered results, select recipients, and
// generate an RFQ draft. Manages its own state + polling.
function SupplierSearch({ projectId }: { projectId: string }) {
  const [pkg, setPkg] = useState('water')
  const [radius, setRadius] = useState(75)
  const [result, setResult] = useState<SupplierSearchResult | null>(null)
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [draft, setDraft] = useState<PersistedRfq | null>(null)
  const [generating, setGenerating] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // Load any prior results when the package changes.
  useEffect(() => {
    let alive = true
    setResult(null); setSelected({}); setErr(null)
    getFoundSuppliers(projectId, pkg)
      .then((r) => { if (!alive) return; setResult(r); if (r.status === 'searching') setSearching(true) })
      .catch(() => {})
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

  const generate = async () => {
    setGenerating(true); setErr(null)
    try {
      const rfq = await generateRfq(projectId, pkg, selectedIds)
      setDraft(rfq)
    } catch (e) {
      setErr('Could not generate RFQ — selected suppliers may not have a discovered email.')
    } finally { setGenerating(false) }
  }

  const tiers = (result && result.tiers) || []
  const total = tiers.reduce((n, t) => n + t.suppliers.length, 0)

  return (
    <>
      {/* Controls */}
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:16px 18px;margin-bottom:16px')}>
        <div style={css('display:flex;align-items:center;gap:8px;margin-bottom:13px')}>
          <span style={css('width:24px;height:24px;border-radius:7px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={14} fill d={SPARKLE_SM} /></span>
          <h2 style={css('margin:0;font-size:14px;font-weight:600;flex:1')}>Find suppliers near the jobsite</h2>
        </div>
        <div style={css('display:flex;gap:7px;flex-wrap:wrap;margin-bottom:14px')}>
          {BUY_PACKAGES.map((p) => (
            <Box as="button" key={p.key} onClick={() => setPkg(p.key)}
              style={css(`height:32px;padding:0 13px;border-radius:8px;font-size:12.5px;font-weight:600;border:1px solid ${pkg === p.key ? 'var(--primary)' : 'var(--border)'};background:${pkg === p.key ? 'var(--primary-soft)' : 'var(--panel)'};color:${pkg === p.key ? 'var(--primary)' : 'var(--text-2)'}`)}
              hover="background:var(--panel-2)">{p.label}</Box>
          ))}
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

      {/* Results */}
      {searching && total === 0 && (
        <div style={css('padding:30px;text-align:center;font-size:13px;color:var(--text-3)')}>Searching Google Places & discovering supplier emails…</div>
      )}
      {!searching && result && total === 0 && (
        <div style={css('padding:30px;text-align:center;font-size:13px;color:var(--text-3)')}>No suppliers found yet — run a search for {pkgLabel(pkg)}.</div>
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
              <FoundSupplierCard key={sup.id} sup={sup} checked={!!selected[sup.id]} onToggle={() => toggle(sup.id)} />
            ))}
          </div>
        </div>
      ))}

      {/* Action bar */}
      {selectedIds.length > 0 && (
        <div style={css('position:sticky;bottom:14px;display:flex;align-items:center;gap:13px;background:var(--panel);border:1px solid var(--primary-soft);box-shadow:var(--shadow-md);border-radius:13px;padding:12px 16px;margin-top:8px')}>
          <span style={css('font-size:13px;font-weight:600;flex:1')}>{selectedIds.length} supplier{selectedIds.length > 1 ? 's' : ''} selected for {pkgLabel(pkg)}</span>
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

function FoundSupplierCard({ sup, checked, onToggle }: { sup: FoundSupplier; checked: boolean; onToggle: () => void }) {
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
    </div>
  )
}

// Shared RFQ draft review + send modal. Editable subject/body/recipients; send
// is the user-approval step (Gmail, or the logging mock when unconfigured).
function RfqReviewModal({ projectId, rfq, onClose }: { projectId: string; rfq: PersistedRfq; onClose: () => void }) {
  const [subject, setSubject] = useState(rfq.subject)
  const [body, setBody] = useState(rfq.body)
  const [recipients, setRecipients] = useState<RfqRecipient[]>(rfq.recipients || [])
  const [status, setStatus] = useState(rfq.status)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const sent = status === 'Sent'

  const dropRecipient = (email: string) => setRecipients((rs) => rs.filter((r) => r.email !== email))

  const send = async () => {
    setBusy(true); setErr(null)
    try {
      await saveRfq(projectId, rfq.id, { subject, body, recipients })
      const out = await sendRfq(projectId, rfq.id)
      setRecipients(out.recipients || [])
      setStatus(out.status)
    } catch (e) { setErr('Send failed. Is the backend running?') }
    finally { setBusy(false) }
  }

  return (
    <div style={css('position:fixed;inset:0;z-index:80;display:flex;align-items:center;justify-content:center;padding:20px')}>
      <div onClick={onClose} style={css('position:absolute;inset:0;background:rgba(15,20,30,.45)')}></div>
      <div style={css('position:relative;width:min(640px,100%);max-height:90vh;overflow-y:auto;background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-lg);animation:pcUp .2s ease both')}>
        <div style={css('display:flex;align-items:center;gap:9px;padding:16px 18px;border-bottom:1px solid var(--border)')}>
          <span style={css('width:26px;height:26px;border-radius:7px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;flex:none')}><Svg size={15} fill d={SPARKLE_SM} /></span>
          <h2 style={css('margin:0;font-size:15px;font-weight:700;flex:1')}>{sent ? 'RFQ sent' : 'Review RFQ draft'} · {pkgLabel(rfq.package)}</h2>
          {sent && <span style={DcBadge('success')}>Sent</span>}
          <Box as="button" onClick={onClose} style={css('width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--text-2)')} hover="background:var(--panel-2)"><Svg size={17} d='M6 6l12 12M18 6 6 18' /></Box>
        </div>
        <div style={css('padding:18px;display:flex;flex-direction:column;gap:16px')}>
          <div>
            <label style={fieldLabel}>Subject</label>
            <input value={subject} disabled={sent} onChange={(e) => setSubject(e.target.value)} style={fieldInput} />
          </div>
          <div>
            <label style={fieldLabel}>Recipients ({recipients.length})</label>
            <div style={css('display:flex;flex-direction:column;gap:6px')}>
              {recipients.length === 0 && <div style={css('font-size:12.5px;color:var(--text-3)')}>No recipients.</div>}
              {recipients.map((r) => (
                <div key={r.email} style={css('display:flex;align-items:center;gap:9px;padding:7px 11px;border:1px solid var(--border);border-radius:9px;background:var(--panel-2)')}>
                  <div style={css('flex:1;min-width:0')}><div style={css('font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{r.name}</div><div style={css('font-size:11.5px;color:var(--text-3)')}>{r.email}</div></div>
                  {r.sentMessageId
                    ? <span style={css(`font-size:11px;font-weight:600;color:${r.sentMessageId.startsWith('error') ? 'var(--danger)' : 'var(--success)'}`)}>{r.sentMessageId.startsWith('error') ? 'Failed' : 'Sent'}</span>
                    : !sent && <Box as="button" onClick={() => dropRecipient(r.email)} style={css('width:24px;height:24px;border-radius:6px;color:var(--text-3);display:flex;align-items:center;justify-content:center')} hover="background:var(--danger-soft);color:var(--danger)"><Svg size={14} sw={2.2} d="M18 6 6 18M6 6l12 12" /></Box>}
                </div>
              ))}
            </div>
          </div>
          <div>
            <label style={fieldLabel}>Message</label>
            <textarea value={body} disabled={sent} onChange={(e) => setBody(e.target.value)} rows={12}
              style={{ ...css('width:100%;padding:11px 13px;border-radius:10px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:13px;line-height:1.55;resize:vertical;font-family:inherit') }} />
          </div>
          {err && <div style={css('font-size:12.5px;color:var(--danger)')}>{err}</div>}
        </div>
        <div style={css('display:flex;align-items:center;gap:10px;padding:14px 18px;border-top:1px solid var(--border)')}>
          <span style={css('flex:1;font-size:11.5px;color:var(--text-3)')}>{sent ? 'Delivered to recipients above.' : 'Sending delivers to all recipients via Gmail (or a logging mock if unconfigured).'}</span>
          <Box as="button" onClick={onClose} style={css('height:36px;padding:0 14px;border-radius:9px;border:1px solid var(--border);font-size:13px;font-weight:600')} hover="background:var(--panel-2)">{sent ? 'Close' : 'Cancel'}</Box>
          {!sent && (
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
  return (
    <>
      <SupplierSearch projectId={m.activeProject.id} />
      <div style={css('margin-top:26px')}>
        <div style={css('display:flex;align-items:center;justify-content:space-between;margin-bottom:14px')}><h2 style={css('margin:0;font-size:15px;font-weight:600')}>Saved suppliers <span style={css('color:var(--text-3);font-weight:500')}>· network</span></h2></div>
        <div style={css('display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px')}>
          {m.suppliers.map((x, i) => <SupplierCard key={i} x={x} />)}
        </div>
      </div>
    </>
  )
}

/* ----------------------------------------------------------------- RFQs tab */
// Lists RFQs generated from the supplier search, newest first. Click one to
// review/send it via the shared modal.
function GeneratedRfqsPanel({ projectId }: { projectId: string }) {
  const [rfqs, setRfqs] = useState<PersistedRfq[] | null>(null)
  const [open, setOpen] = useState<PersistedRfq | null>(null)

  const load = () => listGeneratedRfqs(projectId).then(setRfqs).catch(() => setRfqs([]))
  useEffect(() => { load() }, [projectId])

  if (!rfqs || rfqs.length === 0) return null
  return (
    <div style={css('margin-bottom:18px')}>
      <h2 style={css('margin:0 0 12px;font-size:15px;font-weight:600')}>Generated RFQs <span style={css('color:var(--text-3);font-weight:500')}>· {rfqs.length}</span></h2>
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow-sm);overflow:hidden')}>
        {rfqs.map((rq) => (
          <Box key={rq.id} onClick={() => setOpen(rq)} style={css('display:flex;align-items:center;gap:12px;padding:13px 16px;border-bottom:1px solid var(--border);cursor:pointer')} hover="background:var(--panel-2)">
            <div style={css('flex:1;min-width:0')}>
              <div style={css('font-size:13.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{rq.subject}</div>
              <div style={css('font-size:11.5px;color:var(--text-3);margin-top:1px')}>{pkgLabel(rq.package)} · {(rq.recipients || []).length} recipient{(rq.recipients || []).length === 1 ? '' : 's'}</div>
            </div>
            <span style={DcBadge(rq.status === 'Sent' ? 'success' : rq.status === 'Draft' ? 'gray' : 'blue')}>{rq.status}</span>
          </Box>
        ))}
      </div>
      {open && <RfqReviewModal projectId={projectId} rfq={open} onClose={() => { setOpen(null); load() }} />}
    </div>
  )
}

function TabRfqs({ m }: MProps) {
  const r = m.rfqSel
  return (
    <>
    <GeneratedRfqsPanel projectId={m.activeProject.id} />
    <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
      <div style={css('overflow-x:auto')}>
        <div style={css('display:flex;min-height:600px;min-width:940px')}>
          <div style={css('width:182px;flex:none;border-right:1px solid var(--border);padding:12px 10px;display:flex;flex-direction:column;gap:2px')}>
            <button style={css('display:flex;align-items:center;gap:7px;height:34px;border-radius:8px;background:var(--primary);color:#fff;font-size:12.5px;font-weight:600;justify-content:center;margin-bottom:10px')}><Svg size={14} sw={2.2} d={PLUS} />New RFQ</button>
            {m.rfqFolders.map((f, i) => (
              <Box key={i} style={css('display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border-radius:8px;font-size:13px;color:var(--text-2)')} hover="background:var(--panel-2)"><span>{f.name}</span><span style={css('font-size:11px;font-weight:600;color:var(--text-3)')}>{f.count}</span></Box>
            ))}
          </div>
          <div style={css('width:300px;flex:none;border-right:1px solid var(--border);display:flex;flex-direction:column')}>
            <div style={css('padding:12px 15px;border-bottom:1px solid var(--border);font-size:13px;font-weight:600;color:var(--text-2)')}>Awaiting Response</div>
            <div style={css('flex:1;overflow-y:auto')}>
              {m.rfqs.map((rr, i) => (
                <div key={i} onClick={rr.onSelect} style={rr.rowStyle}>
                  <div style={rr.logoStyle}>{rr.logo}</div>
                  <div style={css('flex:1;min-width:0')}><div style={css('display:flex;align-items:center;justify-content:space-between;gap:6px')}><span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{rr.sup}</span><span style={css('font-size:11px;color:var(--text-3);white-space:nowrap')}>{rr.time}</span></div><div style={css('font-size:11.5px;color:var(--text-2);font-weight:500;margin:1px 0 3px')}>{rr.pkg}</div><div style={css('font-size:11.5px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{rr.preview}</div></div>
                </div>
              ))}
            </div>
          </div>
          <div style={css('flex:1;min-width:0;display:flex;flex-direction:column')}>
            <div style={css('padding:14px 18px;border-bottom:1px solid var(--border)')}><div style={css('font-size:15px;font-weight:600')}>RFQ: {r.pkg}</div><div style={css('font-size:12.5px;color:var(--text-3);margin-top:1px')}>{r.sup} · Riverside Water Treatment Plant</div></div>
            <div style={css('flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:16px')}>
              {m.thread.map((t, i) => (
                <div key={i} style={css('display:flex;gap:11px')}>
                  <div style={t.avatarStyle}>{t.initials}</div>
                  <div style={css('flex:1;min-width:0')}>
                    <div style={css('display:flex;align-items:center;gap:8px;margin-bottom:4px')}><span style={css('font-size:12.5px;font-weight:600')}>{t.who}</span><span style={css('font-size:11px;color:var(--text-3)')}>{t.time}</span></div>
                    {t.hasSubject && <div style={css('font-size:13px;font-weight:600;margin-bottom:3px')}>{t.subject}</div>}
                    <div style={css('font-size:13px;line-height:1.55;color:var(--text)')}>{t.body}</div>
                    {t.hasAttach && <div style={css('display:inline-flex;align-items:center;gap:7px;margin-top:8px;padding:7px 11px;border:1px solid var(--border);border-radius:9px;background:var(--panel-2);font-size:12px;font-weight:500')}><Svg size={14} sw={1.8} stroke="var(--danger)" d='M14 3v5h5" /><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z' />{t.attach}</div>}
                  </div>
                </div>
              ))}
            </div>
            <div style={css('padding:12px 18px;border-top:1px solid var(--border)')}>
              <div style={css('display:flex;align-items:center;gap:8px;padding:10px 12px;border:1px solid var(--primary-soft);background:var(--primary-softer);border-radius:10px;margin-bottom:10px')}><span style={css('color:var(--primary);flex:none')}><Svg size={15} fill d={SPARKLE_SM} /></span><span style={css('font-size:12.5px;color:var(--text);flex:1')}><strong style={css('color:var(--primary)')}>AI follow-up:</strong> "Hi Dana, checking in on our sewer RFQ — any update on timing?"</span><Box as="button" style={css('font-size:12px;font-weight:600;color:var(--primary);white-space:nowrap')} hover="text-decoration:underline">Use</Box></div>
              <div style={css('display:flex;align-items:center;gap:10px;border:1px solid var(--border);border-radius:10px;padding:8px 8px 8px 14px')}><span style={css('font-size:13px;color:var(--text-3);flex:1')}>Reply to {r.sup}…</span><button style={css('height:32px;padding:0 14px;border-radius:8px;background:var(--primary);color:#fff;font-size:12.5px;font-weight:600')}>Send</button></div>
            </div>
          </div>
          <div style={css('width:240px;flex:none;border-left:1px solid var(--border);padding:16px;display:flex;flex-direction:column;gap:16px')}>
            <div style={css('font-size:11px;font-weight:700;letter-spacing:.06em;color:var(--text-3);text-transform:uppercase')}>RFQ Summary</div>
            <div style={css('display:flex;flex-direction:column;gap:13px')}>
              <div><div style={css('font-size:11.5px;color:var(--text-3);margin-bottom:2px')}>Supplier</div><div style={css('font-size:13px;font-weight:600')}>{r.sup}</div></div>
              <div><div style={css('font-size:11.5px;color:var(--text-3);margin-bottom:2px')}>Package</div><div style={css('font-size:13px;font-weight:600')}>{r.pkg}</div></div>
              <div><div style={css('font-size:11.5px;color:var(--text-3);margin-bottom:2px')}>Due date</div><div style={css('font-size:13px;font-weight:600')}>Jun 20, 2026</div></div>
              <div><div style={css('font-size:11.5px;color:var(--text-3);margin-bottom:4px')}>Status</div><span style={r.statusBadge}>{r.status}</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
    </>
  )
}

/* --------------------------------------------------------------- Quotes tab */
function TabQuotes({ m }: MProps) {
  const gridCols = 'minmax(180px,1.6fr) 130px 110px 92px 110px 96px 92px'
  return (
    <>
      <div style={css('display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px')}>
        <h2 style={css('margin:0;font-size:15px;font-weight:600')}>Quotes received <span style={css('color:var(--text-3);font-weight:500')}>· 9</span></h2>
        <Box as="button" onClick={m.openCompare} style={css('display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 14px;border-radius:9px;background:var(--primary);color:#fff;font-size:13px;font-weight:600;box-shadow:var(--shadow-sm)')} hover="background:var(--primary-2)"><Svg size={15} d='M3 6h18M3 12h18M3 18h18' />Compare Water Utilities (3)</Box>
      </div>
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
        <div style={css('overflow-x:auto')}><div style={css('min-width:720px')}>
          <div style={{ display: 'grid', gridTemplateColumns: gridCols, ...css('gap:10px;padding:10px 16px;border-bottom:1px solid var(--border);font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--text-3);text-transform:uppercase') }}><span>Supplier</span><span>Package</span><span style={css('text-align:right')}>Quote</span><span style={css('text-align:right')}>Freight</span><span style={css('text-align:right')}>Total</span><span style={css('text-align:right')}>Lead</span><span style={css('text-align:right')}>Received</span></div>
          {m.quotes.map((q, i) => (
            <Box key={i} onClick={q.onOpen} style={{ display: 'grid', gridTemplateColumns: gridCols, ...css('gap:10px;padding:13px 16px;border-bottom:1px solid var(--border);align-items:center;cursor:pointer') }} hover="background:var(--panel-2)">
              <div style={css('display:flex;align-items:center;gap:10px;min-width:0')}><div style={q.logoStyle}>{q.logo}</div><span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>{q.sup}</span></div>
              <span style={css('font-size:12px;color:var(--text-2)')}>{q.pkg}</span>
              <span style={css("text-align:right;font-size:13px;font-family:'JetBrains Mono',monospace")}>{q.amount}</span>
              <span style={css("text-align:right;font-size:13px;font-family:'JetBrains Mono',monospace;color:var(--text-2)")}>{q.freight}</span>
              <span style={css("text-align:right;font-size:13.5px;font-weight:700;font-family:'JetBrains Mono',monospace")}>{q.total}</span>
              <span style={css("text-align:right;font-size:12.5px;font-family:'JetBrains Mono',monospace")}>{q.lead}</span>
              <span style={css('text-align:right;font-size:12px;color:var(--text-3)')}>{q.date}</span>
            </Box>
          ))}
        </div></div>
      </div>
    </>
  )
}

/* ------------------------------------------------------------- Compare tab */
function TabCompare({ m }: MProps) {
  return (
    <>
      <Box as="button" onClick={m.closeCompare} style={css('display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:500;color:var(--text-2);margin-bottom:14px')} hover="color:var(--text)"><Svg size={16} d='m15 18-6-6 6-6' />Back to quotes</Box>
      <div style={css('margin-bottom:16px')}><h2 style={css('margin:0;font-size:19px;font-weight:700;letter-spacing:-.02em')}>Water Utilities — Quote Comparison</h2><p style={css('margin:4px 0 0;font-size:13px;color:var(--text-2)')}>3 suppliers · 42 line items · budget $679,600</p></div>
      <div style={css('display:grid;grid-template-columns:minmax(0,1.7fr) 320px;gap:16px;align-items:start')}>
        <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
          <div style={css('overflow-x:auto')}><div style={css('min-width:560px')}>
            <div style={css('display:flex;align-items:stretch;border-bottom:1px solid var(--border)')}>
              <div style={css('width:140px;flex:none;padding:16px')}></div>
              {m.cmp.suppliers.map((su, i) => (
                <div key={i} style={css('flex:1;padding:16px 10px;display:flex;flex-direction:column;align-items:center;gap:8px;text-align:center;border-left:1px solid var(--border)')}>
                  <div style={su.logoStyle}>{su.logo}</div>
                  <div style={css('font-size:12.5px;font-weight:600;line-height:1.2')}>{su.name}</div>
                  {su.rec && <span style={css('display:inline-flex;align-items:center;gap:4px;font-size:10.5px;font-weight:700;color:var(--success);background:var(--success-soft);padding:2px 8px;border-radius:999px')}><Svg size={11} sw={3} d='m5 12 5 5L20 7' />Recommended</span>}
                </div>
              ))}
            </div>
            {m.cmp.rows.map((row, i) => (
              <div key={i} style={css('display:flex;align-items:stretch;border-bottom:1px solid var(--border)')}>
                <div style={css('width:140px;flex:none;padding:14px 16px;display:flex;align-items:center;font-size:12.5px;font-weight:600;color:var(--text-2)')}>{row.label}</div>
                {row.cells.map((cell, j) => (
                  <div key={j} style={cell.style}>{cell.best && <Svg size={13} sw={3} d='m5 12 5 5L20 7' />}{cell.v}</div>
                ))}
              </div>
            ))}
          </div></div>
        </div>
        <div style={css('display:flex;flex-direction:column;gap:14px;position:sticky;top:72px')}>
          <div style={css('background:var(--primary-softer);border:1px solid var(--primary-soft);border-radius:16px;padding:18px;box-shadow:var(--shadow-md)')}>
            <div style={css('display:flex;align-items:center;gap:8px;margin-bottom:14px')}><span style={css('width:28px;height:28px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center')}><Svg size={16} fill d={SPARKLE} /></span><span style={css('font-size:13px;font-weight:700;color:var(--primary)')}>AI Recommendation</span></div>
            <div style={css('display:flex;align-items:center;gap:11px;padding:12px;background:var(--panel);border-radius:12px;margin-bottom:14px')}><div style={css('width:40px;height:40px;border-radius:10px;background:#0a4d8c;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px')}>FW</div><div><div style={css('font-size:11px;color:var(--text-3)')}>Recommended supplier</div><div style={css('font-size:15px;font-weight:700')}>Ferguson Waterworks</div></div></div>
            <div style={css('display:flex;flex-direction:column;gap:9px;margin-bottom:16px')}>
              {['Lowest delivery risk (score 94)', 'Fastest lead time at 14 days', 'Within 1% of lowest total bid'].map((t, i) => (
                <div key={i} style={css('display:flex;gap:8px;font-size:12.5px;line-height:1.4')}><Svg size={15} sw={2.4} stroke="var(--success)" d='m5 12 5 5L20 7' style={{ flex: 'none', marginTop: 1 }} /><span>{t}</span></div>
              ))}
            </div>
            <button style={css('width:100%;height:38px;border-radius:9px;background:var(--primary);color:#fff;font-size:13px;font-weight:600')}>Select supplier & issue PO</button>
          </div>
          <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:14px 16px')}><div style={css('font-size:11.5px;color:var(--text-3);margin-bottom:3px')}>Projected savings vs. budget</div><div style={css("font-size:22px;font-weight:700;color:var(--success);font-family:'JetBrains Mono',monospace")}>$184,000</div><div style={css('font-size:11.5px;color:var(--text-3);margin-top:2px')}>27% under the $679.6K allowance</div></div>
        </div>
      </div>
    </>
  )
}

/* ------------------------------------------------------------- Timeline tab */
function TabTimeline({ m }: MProps) {
  return (
    <>
      <div style={css('display:flex;align-items:flex-start;gap:11px;padding:14px 16px;border:1px solid var(--warn-soft);background:var(--warn-soft);border-radius:13px;margin-bottom:16px')}>
        <span style={css('color:var(--warn);flex:none;margin-top:1px')}><Svg size={18} d='M12 4 2.8 19.5h18.4z" /><path d="M12 10v4M12 17.2v.3' /></span>
        <div style={{ flex: 1 }}><div style={css('font-size:13.5px;font-weight:600')}>Storm Drain quotes delayed</div><div style={css('font-size:12.5px;color:var(--text-2);margin-top:2px')}>Fortiline has been non-responsive for 4 days, putting the Jul 16 delivery at risk. ProcureAI recommends sending an automated follow-up.</div></div>
        <button style={css('height:32px;padding:0 12px;border-radius:8px;background:var(--warn);color:#fff;font-size:12px;font-weight:600;white-space:nowrap;flex:none')}>Send follow-up</button>
      </div>
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
      <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:20px')}>
        <h2 style={css('margin:0 0 18px;font-size:15px;font-weight:600')}>Milestones</h2>
        <div style={css('display:flex;flex-direction:column')}>
          {m.milestones.map((mm, i) => (
            <div key={i} style={css('display:flex;gap:15px')}>
              <div style={css('display:flex;flex-direction:column;align-items:center;flex:none')}><span style={mm.dotStyle}></span><span style={css('flex:1;width:2px;background:var(--border);min-height:26px')}></span></div>
              <div style={css('flex:1;padding-bottom:18px;margin-top:-3px')}><div style={css('display:flex;align-items:center;gap:10px;flex-wrap:wrap')}><span style={css('font-size:13.5px;font-weight:600')}>{mm.name}</span><span style={mm.statusBadge}>{mm.status}</span><span style={css("font-size:12px;color:var(--text-3);font-family:'JetBrains Mono',monospace")}>{mm.date}</span></div><div style={css('font-size:12.5px;color:var(--text-2);margin-top:3px')}>{mm.desc}</div></div>
            </div>
          ))}
        </div>
      </div>
    </>
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
