import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import Flow from './Flow'
import HeroField from './HeroField'
import Marquee from './Marquee'

// Proq landing page: Procurement-as-a-Service for general contractors.
// Section order: hero → the pain (marquee + proof strip) → what we do (light)
// → the flow (the centrepiece) → what's in a buyout (light) → who it's for +
// how we charge → footer CTA.

// Every CTA opens a conversation by email unless VITE_DEMO_URL points them at
// a scheduling link instead.
const CONTACT_EMAIL = 'proqrfq@gmail.com'
const MAILTO = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Proq: run a buyout for us')}`
const CTA_URL = import.meta.env.VITE_DEMO_URL || MAILTO

function Cta({ variant = 'primary', size, className = '', children }: {
  variant?: 'primary' | 'ghost'
  size?: 'lg'
  className?: string
  children: ReactNode
}) {
  const cls = `btn btn--${variant}${size ? ` btn--${size}` : ''}${className ? ` ${className}` : ''}`
  return <a className={cls} href={CTA_URL}>{children}</a>
}

const STATS = [
  { n: '≈40%', l: 'of a project’s cost is materials.', s: 'Contrary Research / Kojo' },
  { n: '+7.1%', l: 'nonresidential input prices, year over year.', s: 'AGC, 2026' },
  { n: '+21%', l: 'steel. Aluminum is up 33%.', s: 'AGC, 2026' },
  { n: '53%', l: 'of contractors rank materials cost a top concern for 2026.', s: 'AGC, 2026' },
  { n: '50–60%', l: 'of a PE’s week goes to submittal and procurement paperwork.', s: 'BuildSync' },
  { n: '3–5%', l: 'saved on materials from pricing transparency alone.', s: 'Kojo' },
]

const VALUES = [
  {
    l: 'You approve every award. We do everything else.',
    d: 'Takeoff, BOM, packaging, sourcing, RFQs, chasing, leveling, PO drafting and expediting are ours. The award and the PO signature are yours, every time.',
  },
  {
    l: 'No new software for your PEs.',
    d: 'Approvals, exceptions and delivery updates land in email, Slack or Teams. Nothing to learn, no dashboard to remember to check.',
  },
  {
    l: 'Paid on awarded spend, not hours.',
    d: 'A setup fee and a capped percentage of what you award through us. If the first package doesn’t beat your budget line, it’s free.',
  },
  {
    l: 'Neutral. We take zero supplier money.',
    d: 'No rebates, no preferred vendors, no marketplace fees. The recommendation is the lowest delivered cost that makes your date, and nothing else.',
  },
]

const INCLUDED = [
  { t: 'Takeoff & BOM', d: 'Quantities off the plan set, by sheet and station, checked against every addendum.', human: true },
  { t: 'Packaging', d: 'Lines grouped into scopes a supplier can price in full: water, sanitary, storm, electrical.' },
  { t: 'Sourcing', d: 'Suppliers matched by scope and haul distance, starting with the ones you already trust.' },
  { t: 'RFQ + chase', d: 'RFQs sent from your address. Follow-ups on their schedule, not yours, until the quote lands.' },
  { t: 'Quote leveling', d: 'Every reply parsed to the line: unit, extended, freight, lead time. Substitutions flagged.' },
  { t: 'Award recommendation', d: 'Lowest delivered cost that makes the date. Split only when the saving beats the second freight.', human: true },
  { t: 'POs + expediting', d: 'POs drafted per supplier, confirmations chased, delivery dates tracked against the pour.', human: true },
  { t: 'Reporting', d: 'Who approved what, at what price, when: a record for the owner, the lender and closeout.' },
]

const WHO = [
  {
    t: 'Commercial & institutional GCs',
    meta: [['Revenue', '$20–150M'], ['Purchasing dept', 'None'], ['Who buys today', 'Project engineers']],
    d: 'No purchasing department, so the buy falls to project engineers between RFIs and submittals. We take the full materials buy for a project or a single package, and your PEs get their week back. The award still crosses their desk; the sixty emails behind it don’t.',
  },
  {
    t: 'Self-perform & civil',
    meta: [['Scopes', 'Pipe, structures, rebar, aggregate'], ['Takeoff from', 'Plan and profile sheets'], ['Tied to', 'The pour']],
    d: 'Pipe, structures, aggregates and rebar bought against the station and the pour date. We run the takeoff off the plan-and-profile sheets, price by haul distance, and keep every delivery date tied to the schedule it feeds.',
  },
  {
    t: 'MEP long-lead',
    meta: [['Equipment', 'Switchgear, RTUs, generators'], ['Lead times', '30–60 weeks'], ['Watch for', 'Slips before they hit the schedule']],
    d: 'Switchgear, RTUs, generators and transformers with lead times measured in quarters. We release early, hold suppliers to their dates in writing, and flag a slip the week it happens rather than the week it lands.',
  },
]

function Nav() {
  const [solid, setSolid] = useState(false)
  useEffect(() => {
    const onScroll = () => setSolid(window.scrollY > 24)
    onScroll()
    addEventListener('scroll', onScroll, { passive: true })
    return () => removeEventListener('scroll', onScroll)
  }, [])
  return (
    <nav className={`nav${solid ? ' nav--solid' : ''}`} aria-label="Primary">
      <a className="nav__brand" href="#top">
        <img src="/proq-icon.png" alt="" />
        Proq
      </a>
      <div className="nav__links">
        <a href="#what">What we do</a>
        <a href="#flow">How it works</a>
        <a href="#who">Who it’s for</a>
        <Cta variant="ghost">Talk to us</Cta>
      </div>
    </nav>
  )
}

function Accordion() {
  const [open, setOpen] = useState(0)
  return (
    <div className="acc">
      {WHO.map((w, i) => {
        const isOpen = open === i
        // React 18 drops boolean `inert` (it is not in its attribute table), so
        // the closed state is written as an empty string, which it passes through.
        const inert = isOpen ? undefined : ('' as unknown as boolean)
        return (
          <div className="acc__item" key={w.t}>
            <h3>
              <button
                type="button"
                className="acc__btn"
                aria-expanded={isOpen}
                aria-controls={`who-panel-${i}`}
                id={`who-btn-${i}`}
                onClick={() => setOpen(isOpen ? -1 : i)}
              >
                <span>{w.t}</span>
                <span className="acc__plus" aria-hidden="true" />
              </button>
            </h3>
            <div
              className="acc__panel"
              data-open={isOpen}
              id={`who-panel-${i}`}
              role="region"
              aria-labelledby={`who-btn-${i}`}
              aria-hidden={!isOpen}
              inert={inert}
            >
              <div>
                <div className="acc__inner">
                  <div className="acc__meta">
                    {w.meta.map(([k, v]) => (
                      <span key={k}><b>{k}</b><em>{v}</em></span>
                    ))}
                  </div>
                  <p className="body">{w.d}</p>
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// A quiet wireframe wave under the footer CTA: three sine curves in the
// band's line colour, nothing more.
function Wave() {
  const path = (amp: number, phase: number, y: number) => {
    let d = `M0 ${y}`
    for (let x = 0; x <= 1440; x += 20) {
      const yy = y + Math.sin(x / 190 + phase) * amp + Math.sin(x / 61 + phase * 2) * amp * 0.25
      d += ` L${x} ${yy.toFixed(1)}`
    }
    return d
  }
  return (
    <svg className="foot__wave" viewBox="0 0 1440 200" preserveAspectRatio="none" aria-hidden="true">
      <g fill="none" stroke="var(--line)" strokeWidth="1">
        <path d={path(22, 0, 70)} />
        <path d={path(26, 1.4, 110)} />
        <path d={path(18, 2.9, 150)} />
        <path d={path(24, 4.1, 185)} />
      </g>
    </svg>
  )
}

export default function Landing() {
  return (
    <div id="top">
      <Nav />

      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <header className="band band--dark hero">
        <HeroField />
        <div className="hero__shade" aria-hidden="true" />
        <div className="shell hero__inner">
          <span className="kicker">Procurement-as-a-Service · General contractors</span>
          <h1 className="h-display hero__title" style={{ marginTop: 22 }}>
            <span style={{ display: 'block' }}>Send us the plan set.</span>
            <span style={{ display: 'block' }}>We run the buy.</span>
          </h1>
          <p className="lede hero__lede">
            Proq runs materials procurement for general contractors: takeoff, sourcing, RFQs, quote leveling, awards and expediting. AI agents do the work. Your team approves every award.
          </p>
          <div className="hero__ctas">
            <Cta size="lg">Request a buyout</Cta>
            <a className="btn btn--ghost btn--lg" href="#flow">See how it works</a>
          </div>
          <div className="hero__foot mono">
            <span>Takeoff → BOM → RFQ → Award → PO → Delivery</span>
            <a href="#pain">Explore ↓</a>
          </div>
        </div>
      </header>

      {/* ── The pain ─────────────────────────────────────────────────── */}
      <section id="pain" className="band band--dark section pain">
        <div className="shell">
          <span className="kicker">The week that isn’t building</span>
          <h2 className="h-section" style={{ marginTop: 22 }}>The buy is a full-time job nobody was hired for.</h2>
          <p className="lede" style={{ marginTop: 24, maxWidth: '52ch' }}>
            Project engineers run procurement between RFIs, submittals and the field. Quotes sit in inboxes, lead times live in someone’s head, and the schedule finds out last.
          </p>
        </div>
        <Marquee />
        <div className="shell">
          <div className="stats">
            {STATS.map((s) => (
              <div className="stat" key={s.n + s.s}>
                <span className="stat__n">{s.n}</span>
                <span className="stat__l">{s.l}</span>
                <span className="stat__s">{s.s}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── What we do ───────────────────────────────────────────────── */}
      <section id="what" className="band band--light section">
        <div className="shell">
          <div className="head">
            <h2 className="h-section">We run the buy. You sign the award.</h2>
            <p className="lede">
              Proq is a procurement service, not another login. Send the plan set; our agents take off quantities, build the BOM, package the scope, find suppliers, send and chase RFQs, level the quotes and recommend the award. Your team approves it in the tools it already uses.
            </p>
          </div>
          <div className="values">
            {VALUES.map((v) => (
              <div className="value" key={v.l}>
                <h3 className="value__l">{v.l}</h3>
                <p className="body value__d">{v.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── The flow ─────────────────────────────────────────────────── */}
      <Flow />

      {/* ── What's in a buyout ───────────────────────────────────────── */}
      <section id="included" className="band band--light section">
        <div className="shell">
          <div className="head">
            <div>
              <span className="kicker">Included in every package</span>
              <h2 className="h-section" style={{ marginTop: 22 }}>What’s in a buyout.</h2>
            </div>
            <p className="lede">
              Eight pieces of work, three of them signed by a person on your team. Everything else runs in the background and shows up as a status, not a task.
            </p>
          </div>
          <div className="included">
            {INCLUDED.map((it, i) => (
              <div className="inc" key={it.t}>
                <span className="inc__n">{String(i + 1).padStart(2, '0')}</span>
                <h3 className="inc__t">
                  {it.t}
                  {it.human && <span className="tag"><i />Human approves</span>}
                </h3>
                <p className="body inc__d">{it.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Who it's for + how we charge ─────────────────────────────── */}
      <section id="who" className="band band--dark section who">
        <div className="shell">
          <h2 className="h-section">Built for the GC who buys between RFIs.</h2>
          <Accordion />
          <div className="pricing" id="pricing">
            <div>
              <span className="kicker">How we charge</span>
              <h3 className="h-sub" style={{ marginTop: 18 }}>A setup fee, then a share of awarded spend. Capped.</h3>
            </div>
            <p className="lede">
              A setup fee to onboard the project, then a percentage of the spend you award through us, capped per package. No seats, no hourly, no supplier kickbacks. The first package is free if we don’t beat your budget line.
            </p>
          </div>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────────── */}
      <footer className="band band--dark foot">
        <Wave />
        <div className="shell">
          <div className="foot__inner">
            <h2 className="h-section">The plan set is already on your desk.</h2>
            <div className="foot__cta">
              <Cta variant="ghost" size="lg">Start a conversation ↗</Cta>
            </div>
          </div>
          <div className="foot__meta">
            <span>© {new Date().getFullYear()} Proq</span>
            <span>Procurement-as-a-Service for general contractors</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
