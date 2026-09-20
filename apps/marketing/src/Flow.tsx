import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent, ReactNode } from 'react'
import { Check, usePrefersReducedMotion } from './lib'

// "One buyout, start to finish.": four auto-advancing steps over an
// illustrative panel that mocks the actual work: the plan set arriving, the
// buy being built and connected, the sourcing round updating in place, and
// the award landing in the team's chat for a one-line approval.

const STEP_MS = 5000
const TICK_MS = 100

type Step = { n: string; label: string; caption: string }

const STEPS: Step[] = [
  { n: '01', label: 'The plan set lands', caption: 'A Rev B plan set arrives in the inbox. The agent picks it up.' },
  { n: '02', label: 'Build the buy', caption: 'The agent takes off quantities, drafts the BOM and cuts the packages.' },
  { n: '03', label: 'Source, quote, level', caption: 'RFQs go out, follow-ups go out, quotes come back leveled to the line.' },
  { n: '04', label: 'Approve in your inbox', caption: 'The award lands where your team already works. One reply, POs issued.' },
]

// The connected-system cards on the right of the stage, with the status each
// one shows at step 2 (built) and step 3 (sourced). The award card only exists
// once there is something to recommend.
type Sys = {
  chip: string
  color: string
  title: string
  built?: [string, string]
  sourced: [string, string]
  ok?: boolean
}

const SYSTEMS: Sys[] = [
  {
    chip: 'Bill of materials', color: '#2f8ce0',
    title: 'Riverside WTP · Rev B · 212 lines',
    built: ['Drafted from 142 sheets', 'Sent to J. Ortiz for engineer review'],
    sourced: ['Approved by J. Ortiz', 'Addendum 2 reflected · 12" DI main now Cl 52'],
    ok: true,
  },
  {
    chip: 'Buy packages', color: '#c8a24a',
    title: 'Water utilities · Sanitary · Storm · Electrical',
    built: ['4 packages cut', 'Water utilities first · 38 lines · need by 14 Oct'],
    sourced: ['RFQs sent to 7 suppliers', 'Follow-ups scheduled · 2 chased this morning'],
  },
  {
    chip: 'Suppliers', color: '#4fb286',
    title: 'Ferguson Waterworks · Core & Main · HD Supply +4',
    built: ['7 matched within 60 mi', '3 already on your vendor list'],
    sourced: ['Quotes received 5 / 7', 'Parsed to the line · 2 substitutions flagged'],
  },
  {
    chip: 'Award', color: '#f5f5f5',
    title: 'Water utilities package',
    sourced: ['Split award recommended', '$1,620 under best single bid · freight priced in'],
    ok: true,
  },
]

// ── Tabs + timer ────────────────────────────────────────────────────────

export default function Flow() {
  const reduced = usePrefersReducedMotion()
  const [step, setStep] = useState(0)
  const [progress, setProgress] = useState(0)
  const [hover, setHover] = useState(false)
  const [inView, setInView] = useState(true)
  const progressRef = useRef(0)
  const sectionRef = useRef<HTMLElement | null>(null)
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])

  const paused = reduced || hover || !inView

  useEffect(() => {
    if (paused) return
    const id = window.setInterval(() => {
      progressRef.current += TICK_MS / STEP_MS
      if (progressRef.current >= 1) {
        progressRef.current = 0
        setStep((s) => (s + 1) % STEPS.length)
      }
      setProgress(progressRef.current)
    }, TICK_MS)
    return () => window.clearInterval(id)
  }, [paused])

  // Only run the clock while the section is actually on screen.
  useEffect(() => {
    const el = sectionRef.current
    if (!el || typeof IntersectionObserver !== 'function') return
    const io = new IntersectionObserver(([e]) => setInView(e.isIntersecting), { threshold: 0.15 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  const select = useCallback((i: number) => {
    progressRef.current = 0
    setProgress(0)
    setStep(i)
  }, [])

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = STEPS.length
    let next: number | null = null
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % n
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + n) % n
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = n - 1
    if (next === null) return
    e.preventDefault()
    select(next)
    tabRefs.current[next]?.focus()
  }

  return (
    <section
      id="flow"
      ref={sectionRef}
      className="band band--dark section"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="shell">
        <div className="head">
          <h2 className="h-section">One buyout, start to finish.</h2>
          <p className="lede">
            Here is what happens between the plan set landing and the PO going out. The agents do the work across your inbox, your drive and your suppliers. Your team sees the recommendation and the exceptions.
          </p>
        </div>

        <div className="flow-tabs" role="tablist" aria-label="Buyout steps">
          {STEPS.map((s, i) => {
            const active = i === step
            const done = i < step
            return (
              <button
                key={s.n}
                ref={(el) => { tabRefs.current[i] = el }}
                role="tab"
                id={`flow-tab-${i}`}
                aria-selected={active}
                aria-controls="flow-panel"
                tabIndex={active ? 0 : -1}
                className={`flow-tab${done ? ' flow-tab--done' : ''}`}
                onClick={() => select(i)}
                onKeyDown={(e) => onKey(e, i)}
              >
                <span
                  className="flow-tab__bar"
                  style={active ? { transform: `scaleX(${reduced ? 1 : progress})` } : undefined}
                  aria-hidden="true"
                />
                <span className="flow-tab__n">{s.n}</span>
                <span>{s.label}</span>
              </button>
            )
          })}
        </div>

        <div
          id="flow-panel"
          role="tabpanel"
          aria-labelledby={`flow-tab-${step}`}
          className="flow-panel"
        >
          <div className="flow-panel__bar">
            <span key={step} className="fade">{STEPS[step].caption}</span>
            <span className="mono">Illustrative example</span>
          </div>
          <div className="flow-panel__body">
            {step < 3 ? <Stage step={step} /> : <Chat key="chat" />}
          </div>
        </div>
      </div>
    </section>
  )
}

// ── Steps 1–3: inbox card + connected system cards ──────────────────────

type Line = { d: string; x: number; y: number; on: boolean }

function Stage({ step }: { step: number }) {
  const stageRef = useRef<HTMLDivElement | null>(null)
  const sourceRef = useRef<HTMLDivElement | null>(null)
  const cardRefs = useRef<(HTMLDivElement | null)[]>([])
  const [lines, setLines] = useState<Line[]>([])
  const [origin, setOrigin] = useState<{ x: number; y: number } | null>(null)

  const visible = step === 0 ? 3 : step === 1 ? 3 : SYSTEMS.length

  // Draw the connector tree from the plan-set card to every visible system
  // card. Measured from layout (offsetTop/Left), not from the bounding box, so
  // the reveal animation's transform does not skew the geometry.
  useLayoutEffect(() => {
    const stage = stageRef.current
    const src = sourceRef.current
    if (!stage || !src) return

    const rel = (el: HTMLElement) => {
      let x = 0
      let y = 0
      let node: HTMLElement | null = el
      while (node && node !== stage) {
        x += node.offsetLeft
        y += node.offsetTop
        node = node.offsetParent as HTMLElement | null
      }
      return { x, y, w: el.offsetWidth, h: el.offsetHeight }
    }

    const measure = () => {
      if (step === 0 || stage.offsetWidth < 700) {
        setLines([])
        setOrigin(null)
        return
      }
      const s = rel(src)
      const x0 = s.x + s.w
      const y0 = s.y + Math.min(s.h - 24, 92)
      const next: Line[] = []
      let xm = x0
      cardRefs.current.slice(0, visible).forEach((card, i) => {
        if (!card) return
        const c = rel(card)
        const x1 = c.x
        const y1 = c.y + 22
        if (i === 0) xm = x0 + (x1 - x0) / 2
        const on = step === 2 && !!SYSTEMS[i].ok
        next.push({ d: `M${x0} ${y0} H${xm} V${y1} H${x1 - 4}`, x: x1 - 4, y: y1, on })
      })
      setLines(next)
      setOrigin({ x: x0, y: y0 })
    }

    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(stage)
    document.fonts?.ready.then(measure)
    return () => ro.disconnect()
  }, [step, visible])

  return (
    <div className="stage" ref={stageRef}>
      <div className="stage__col">
        <span className="mono">Incoming · Riverside WTP</span>
        <div className="mk" ref={sourceRef}>
          <div className="inbox__head">
            <span className="mk__chip" style={{ '--chip': '#2f8ce0' } as CSSProperties}><i />Inbox</span>
            <span className="inbox__search">Search</span>
          </div>
          <div className="inbox__row inbox__row--on">
            <span className="avatar">DW</span>
            <div style={{ minWidth: 0 }}>
              <div className="inbox__from">Dana Whitfield</div>
              <div className="inbox__subj">Plan set received: Riverside WTP, Rev B, 142 sheets</div>
              <div className="inbox__pre">Rev B is out. Addendum 2 moved the 12" DI main to Cl 52 and…</div>
            </div>
            <span className="inbox__time">8:41 AM</span>
          </div>
          <div className="inbox__row">
            <span className="avatar">CM</span>
            <div style={{ minWidth: 0 }}>
              <div className="inbox__from">Core &amp; Main</div>
              <div className="inbox__subj">RE: Eastgate storm delivery window</div>
              <div className="inbox__pre">Confirming the 24" RCP for the week of the 6th…</div>
            </div>
            <span className="inbox__time">Yesterday</span>
          </div>
          <div className="inbox__msg">
            <h4>Plan set received: Riverside WTP, Rev B, 142 sheets</h4>
            <div className="msg__meta"><b>Dana Whitfield</b><span>PM · to Procurement</span></div>
            <p>
              Rev B is out. Addendum 2 moved the 12" DI main to <strong>Cl 52</strong> and added the bypass on C-401. Can we get the water utilities package priced before the 14th? Pour is the 21st.
            </p>
            <span className="attach"><i>PDF</i>Riverside-WTP_RevB.pdf<span>212 MB</span></span>
          </div>
        </div>
        <p className="picked">↳ Picked up by the agent.</p>
        <div className="extracted">Extracted · C-401 · 12" DI pipe Cl 52 · <em>1,840 LF</em></div>
      </div>

      <div className="stage__col">
        <span className="mono">{step === 2 ? 'Sourcing round · water utilities' : 'The buy'}</span>
        {SYSTEMS.slice(0, visible).map((s, i) => {
          const ghost = step === 0
          const [status, detail] = step === 2 ? s.sourced : s.built ?? s.sourced
          const ok = step === 2 && s.ok
          const fresh = (step === 1) || (step === 2 && i === SYSTEMS.length - 1)
          return (
            <div
              key={s.chip}
              ref={(el) => { cardRefs.current[i] = el }}
              className={`mk sys${ghost ? ' sys--ghost' : ''}${fresh ? ' sys--new' : ''}`}
              style={fresh ? { animationDelay: `${i * 90}ms` } : undefined}
            >
              <span className="mk__chip" style={{ '--chip': s.color } as CSSProperties}><i />{s.chip}<b>· Proq</b></span>
              <div className="sys__title">{s.title}</div>
              <div className={`sys__status${ok ? ' sys__status--ok' : ''}`}>
                {ok && <span className="tick"><Check size={13} /></span>}
                {status}
              </div>
              <div className="sys__detail">{detail}</div>
            </div>
          )
        })}
      </div>

      {lines.length > 0 && (
        <svg className="stage__lines" aria-hidden="true">
          {lines.map((l) => <path key={l.d} d={l.d} />)}
          {origin && <circle cx={origin.x} cy={origin.y} r={3} className="on" />}
          {lines.map((l) => <circle key={`${l.x}-${l.y}`} cx={l.x} cy={l.y} r={3} className={l.on ? 'on' : undefined} />)}
        </svg>
      )}
    </div>
  )
}

// ── Step 4: award delivered in chat ─────────────────────────────────────

function Msg({ who, when, bot, initials, className, children }: {
  who: string; when: string; bot?: boolean; initials?: string; className?: string; children: ReactNode
}) {
  return (
    <div className={`msg fade${className ? ` ${className}` : ''}`}>
      <span className={`msg__av${bot ? ' msg__av--bot' : ''}`}>
        {bot ? <img src="/proq-icon.png" alt="" /> : initials}
      </span>
      <div style={{ minWidth: 0 }}>
        <div className="msg__meta">
          <b>{who}</b>
          {bot && <span className="app">App</span>}
          <span>{when}</span>
        </div>
        <div className="msg__body">{children}</div>
      </div>
    </div>
  )
}

function Chat() {
  return (
    <div className="chat fade">
      <aside className="chat__rail" aria-hidden="true">
        <div className="chat__ws"><i>R</i>Riverside GC</div>
        <div style={{ padding: '12px 0 4px' }}>
          <div className="chat__ch"><small>#</small>field-daily</div>
          <div className="chat__ch chat__ch--on"><small>#</small>riverside-wtp</div>
          <div className="chat__ch"><small>#</small>procurement</div>
          <div className="chat__ch"><small>#</small>submittals</div>
        </div>
      </aside>
      <div className="chat__main">
        <div className="chat__head">
          <span style={{ color: 'inherit', fontSize: 'inherit' }}># riverside-wtp</span>
          <span>Water utilities · award</span>
        </div>

        <Msg who="Proq" when="9:14 AM" bot>
          <div className="msg__card">
            <h5>Riverside WTP · Water utilities award ready</h5>
            Five quoted lines, three vendors. Recommending a split: pipe and hydrants to <strong>Ferguson Waterworks</strong>, valves and fittings to <strong>Core &amp; Main</strong>. <strong>$1,620 under</strong> the best single bid with freight priced in; both inside the 14 Oct need date.
            <ul className="msg__list">
              <li><span className="tick"><Check size={13} /></span>Quotes leveled to the line · 5 of 7 suppliers</li>
              <li><span className="tick"><Check size={13} /></span>Rev B addendum 2 reflected · 12" DI at Cl 52</li>
              <li><span className="tick"><Check size={13} /></span>Freight and lead time priced in · 14d / 16d</li>
            </ul>
            <div className="msg__btns">
              <span className="msg__btn">Approve award</span>
              <span className="msg__btn msg__btn--ghost">See the comparison</span>
            </div>
          </div>
        </Msg>

        <Msg who="Maya Chen" when="9:22 AM" initials="MC" className="msg--reply">
          Approved. Flag me if DI lead time slips.
        </Msg>

        <Msg who="Proq" when="9:22 AM" bot className="msg--confirm">
          Done. POs issued to Core &amp; Main (<strong>PO-1042</strong>) and Ferguson Waterworks (<strong>PO-1043</strong>). I'll post here when delivery is confirmed.
        </Msg>
      </div>
    </div>
  )
}
