import type { ReactNode } from 'react'
import { css } from './lib'
import ActivityFeed from './ActivityFeed'
import ProductMock from './ProductMock'
import { motion, reveal, staggerParent, staggerItem, heroParent, heroItem, hoverLift } from './motion'

// Proq marketing landing page. Ported from the Claude Design component
// "Proq Landing.dc.html"; its three `<sc-if>` switches survive as props.

const DEMO_URL = import.meta.env.VITE_DEMO_URL

const KICKER = 'display:block;font-size:13px;line-height:14px;letter-spacing:0.08em;text-transform:uppercase;color:var(--color-accent-700);margin:0 0 14px'
const H2 = 'font-family:var(--font-heading);font-weight:800;font-size:32px;line-height:42px;letter-spacing:-0.015em;text-box:trim-both cap alphabetic'
const BODY = 'font-size:15.5px;line-height:28px;color:color-mix(in srgb,var(--color-text) 78%,transparent)'
const STEP = 'display:grid;grid-template-columns:minmax(64px,120px) minmax(0,380px) minmax(0,1fr);gap:28px clamp(24px,4vw,72px);align-items:baseline;padding:42px 0'

// Until a scheduling link is configured the design's inert buttons stand in —
// better a dead control than a guessed address. Set VITE_DEMO_URL to wire them.
function Cta({ variant, style, children }: { variant: 'primary' | 'ghost'; style?: string; children: ReactNode }) {
  const className = `btn btn-${variant}`
  return DEMO_URL
    ? <motion.a {...hoverLift} className={className} href={DEMO_URL} style={css(style)}>{children}</motion.a>
    : <motion.button {...hoverLift} type="button" className={className} style={css(style)}>{children}</motion.button>
}

const BEFORE = [
  'Read the plan set page by page, take off quantities',
  'Rebuild the bill of materials in a spreadsheet',
  'Call around for suppliers who cover the scope',
  'Type RFQ emails one vendor at a time',
  'Chase the four who never replied',
  'Retype quotes into a comparison tab, unit by unit',
  'Cut the PO, then chase the delivery date',
  'Update the schedule, then tell everyone about it',
]

const AFTER = [
  'Drawings ingested, quantities extracted, BOM drafted',
  'Materials grouped into buy packages you can review',
  'Suppliers found by scope and haul distance',
  'RFQs written, sent from your address, tracked per vendor',
  'Follow-ups sent on their own schedule, not yours',
  'Quotes parsed to the line, priced against each other',
  'Award recommended with freight and lead time solved',
  'POs issued, deliveries tracked, timeline updated',
]

const STEPS = [
  {
    title: 'Read the project',
    body: 'Civil, utility, storm and electrical sheets, specs and addenda go in as they are. Each plan type lands in its own slot; the agent extracts quantities and returns a bill of materials your engineer edits in place before anything is quoted.',
  },
  {
    title: 'Package the buy',
    body: 'Line items group into the packages a buyer actually sources — water utilities, sanitary sewer, storm drain, electrical — each one a scope a supplier can price in full.',
  },
  {
    title: 'Source and send',
    body: 'Suppliers are found by scope and radius, matched against the ones you already work with, and issued RFQs from your own sending address. Follow-ups go out automatically until a quote arrives.',
  },
  {
    title: 'Compare to the line',
    body: 'Replies are parsed into a line-by-line grid: unit price, extended cost, lead time, freight and haul distance per vendor. Substitutions are flagged. Nothing is retyped.',
  },
  {
    title: 'Solve the award',
    body: 'Lowest delivered cost, fastest delivery, or one supplier for the whole package — the optimizer splits a line only when the material saving beats the second freight charge. You override any cell, then submit.',
  },
  {
    title: 'Run the delivery',
    body: 'POs issue per supplier, deliveries and milestones stay current, lenders and stakeholders get the progress note, and the decision trail is on the record — who approved what, at what price, when.',
  },
]

const SURFACES = [
  { title: 'Procurement', body: 'BOMs, packages, RFQs, quote comparison, awards, POs.', live: true },
  { title: 'Vendor coordination', body: 'Email threads, follow-ups, deliveries, delivery-risk flags.', live: true },
  { title: 'Project timeline', body: 'Milestones, procurement-driven schedule, stakeholder updates.', live: true },
  { title: 'Scheduling', body: 'Look-aheads that move when a lead time moves.', live: false },
  { title: 'Documentation', body: 'Submittals, RFIs, meeting summaries, as-builts.', live: false },
  { title: 'Financial workflows', body: 'Commitments, change orders, pay apps, lender reporting.', live: false },
  { title: 'Subcontractor ops', body: 'Scopes, buyout, compliance, sub schedule alignment.', live: false },
  { title: 'Field operations', body: 'Daily reports, quality tracking, punch, closeout.', live: false },
]

export default function Landing({
  altHeadline = false,
  showProductScreen = true,
  showAgentFeed = true,
}: {
  altHeadline?: boolean
  showProductScreen?: boolean
  showAgentFeed?: boolean
}) {
  const headline = altHeadline
    ? ['The operating system for', 'AI-native general contractors.']
    : ["Contractors don't lose projects building.", 'They lose them coordinating.']

  return (
    <div className="pq-page" style={css('background:var(--color-bg);color:var(--color-text)')}>

      <nav className="nav pq-nav">
        <span className="nav-brand" style={css('display:flex;align-items:center')}>
          <img src="/proq-lockup.png" alt="Proq" style={css('width:124px;height:auto;display:block')} />
        </span>
        <a href="#platform">Platform</a>
        <a href="#screen">Product</a>
        <a href="#vision">Vision</a>
        <Cta variant="primary">Book a demo</Cta>
      </nav>

      <div className="pq-shell">

        <motion.section {...heroParent} style={css('padding:112px 0 84px')}>
          <motion.h1 variants={heroItem} style={css('font-family:var(--font-heading);font-weight:800;font-size:clamp(42px,6.2vw,84px);line-height:clamp(44.5px,6.57vw,89px);letter-spacing:-0.02em;margin:0 0 0 -0.058em;text-box:trim-both cap alphabetic')}>
            {headline.map((line) => <span key={line} style={css('display:block')}>{line}</span>)}
          </motion.h1>
          <motion.p variants={heroItem} style={css('font-size:17px;line-height:28px;max-width:58ch;margin:34px 0 0;text-box:trim-both cap alphabetic')}>
            Proq is an AI platform that runs procurement and project operations for general contractors. Upload the plan set: agents read the drawings, build the bill of materials, package the buy, find suppliers, send and chase RFQs, normalize quotes, award the package and issue the POs. Your team approves. The work executes itself.
          </motion.p>
          <motion.div variants={heroItem} style={css('display:flex;gap:var(--space-3);flex-wrap:wrap;margin-top:28px')}>
            <Cta variant="primary">Book a demo</Cta>
            <a className="btn btn-ghost" href="#screen">See the platform</a>
          </motion.div>
        </motion.section>

        <hr className="hr" style={css('margin:0')} />

        <section style={css('padding:84px 0 70px')}>
          <motion.span {...reveal} style={css(KICKER)}>The week that isn't building</motion.span>
          <motion.h2 {...reveal} style={css(`${H2};margin:0 0 42px;max-width:26ch`)}>A project engineer's week, before and after.</motion.h2>
          <div style={css('display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:28px 72px')}>
            <div>
              <p style={css('font-size:13px;line-height:14px;letter-spacing:0.08em;text-transform:uppercase;color:color-mix(in srgb,var(--color-text) 70%,transparent);margin:0 0 20px')}>
                Today — done by hand
              </p>
              <motion.ul {...staggerParent} style={css('list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:0')}>
                {BEFORE.map((item, i) => (
                  <motion.li
                    key={item}
                    variants={staggerItem}
                    style={css(
                      'font-size:15.5px;line-height:24px;padding:12px 0;border-top:1px solid color-mix(in srgb,var(--color-text) 18%,transparent);color:color-mix(in srgb,var(--color-text) 78%,transparent)' +
                        (i === BEFORE.length - 1 ? ';border-bottom:1px solid color-mix(in srgb,var(--color-text) 18%,transparent)' : ''),
                    )}
                  >
                    {item}
                  </motion.li>
                ))}
              </motion.ul>
            </div>
            <div>
              <p style={css('font-size:13px;line-height:14px;letter-spacing:0.08em;text-transform:uppercase;color:var(--color-accent-700);margin:0 0 20px')}>
                With Proq — done by agents
              </p>
              <motion.ul {...staggerParent} style={css('list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:0')}>
                {AFTER.map((item, i) => (
                  <motion.li
                    key={item}
                    variants={staggerItem}
                    style={css(
                      'font-size:15.5px;line-height:24px;padding:12px 0 12px 24px;border-top:2px solid var(--color-divider);position:relative' +
                        (i === AFTER.length - 1 ? ';border-bottom:2px solid var(--color-divider)' : ''),
                    )}
                  >
                    <span style={css('position:absolute;left:0;top:19px;width:10px;height:10px;background:var(--color-accent)')} />
                    {item}
                  </motion.li>
                ))}
              </motion.ul>
              <motion.p {...reveal} style={css(`${BODY};margin:20px 0 0;max-width:44ch`)}>
                The human stays on the decisions — approve the BOM, approve the award, sign the PO. Everything between those approvals is agent work.
              </motion.p>
            </div>
          </div>
        </section>

        <section id="platform" style={css('padding:70px 0 56px')}>
          <motion.span {...reveal} style={css(KICKER)}>Plan set to purchase order</motion.span>
          {STEPS.map((step, i) => (
            <motion.div {...reveal} key={step.title} style={css(i === 0 ? STEP : `${STEP};border-top:2px solid var(--color-divider)`)}>
              <p style={css("font-family:var(--font-heading);font-weight:800;font-size:15px;line-height:28px;font-feature-settings:'tnum' 1;margin:0")}>
                {String(i + 1).padStart(2, '0')}
              </p>
              <h3 style={css('font-family:var(--font-heading);font-weight:800;font-size:24px;line-height:28px;letter-spacing:-0.01em;margin:0')}>
                {step.title}
              </h3>
              <p style={css(`${BODY};margin:0;max-width:52ch`)}>{step.body}</p>
            </motion.div>
          ))}
        </section>

      </div>

      {showProductScreen && (
        <section id="screen" style={css('border-top:2px solid var(--color-divider);background:var(--color-surface);padding:70px 0 84px')}>
          <div className="pq-shell">
            <div style={css('display:flex;justify-content:space-between;align-items:baseline;gap:28px;flex-wrap:wrap;margin-bottom:28px')}>
              <motion.div {...reveal}>
                <span style={css(KICKER)}>In the product</span>
                <h2 style={css(`${H2};margin:0;max-width:30ch`)}>Five quoted lines, three vendors, one decision.</h2>
              </motion.div>
              <motion.p {...reveal} style={css(`${BODY};margin:0;max-width:46ch`)}>
                Water utilities on the Riverside plant. The agent found a split award worth $1,620 against the best single bid — two POs instead of one, freight priced in. The buyer approves it in a click, or moves a line and watches the number move.
              </motion.p>
            </div>

            <motion.div {...reveal}>
              <ProductMock />
            </motion.div>

            <motion.p {...reveal} style={css('font-size:13px;line-height:28px;color:color-mix(in srgb,var(--color-text) 70%,transparent);margin:14px 0 0')}>
              Quote Comparison, Riverside WTP — recreated from the product.
            </motion.p>
          </div>
        </section>
      )}

      <div className="pq-shell">

        {showAgentFeed && (
          <section className="pq-split" style={css('padding:84px 0')}>
            <motion.div {...reveal}>
              <span style={css(KICKER)}>Always running</span>
              <h2 style={css(`${H2};margin:0`)}>The work happens while nobody is watching.</h2>
              <p style={css(`${BODY};margin:28px 0 0;max-width:48ch`)}>
                Agents don't wait for someone to open a tab. Quotes arrive and get parsed. A vendor goes quiet and gets chased. A saving appears and gets flagged for approval. The feed is the record of work already done.
              </p>
            </motion.div>
            <ActivityFeed />
          </section>
        )}

        <hr className="hr" style={css('margin:0')} />

        <section id="vision" style={css('padding:84px 0 70px')}>
          <motion.span {...reveal} style={css(KICKER)}>Procurement is the wedge</motion.span>
          <motion.h2 {...reveal} style={css('font-family:var(--font-heading);font-weight:800;font-size:clamp(32px,3.6vw,44px);line-height:1.1;letter-spacing:-0.015em;margin:0 0 0 -0.03em;max-width:30ch;text-box:trim-both cap alphabetic')}>
            Every operational workflow in a construction company ends up here.
          </motion.h2>
          <motion.p {...reveal} style={css('font-size:17px;line-height:28px;max-width:58ch;margin:34px 0 42px')}>
            Procurement is where the pain is loudest, the data richest and the ROI provable in one buy. It is also the doorway: the same agents that read a plan set and coordinate a vendor can run the schedule, the submittals, the subs and the money. Contractors stop buying eight tools and start running one operating system.
          </motion.p>
          <motion.div {...staggerParent} style={css('display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:0 clamp(24px,4vw,56px)')}>
            {SURFACES.map((s, i) => (
              <motion.div
                key={s.title}
                variants={staggerItem}
                style={css(
                  'border-top:2px solid var(--color-divider);padding:20px 0' +
                    (i >= SURFACES.length - 2 ? ';border-bottom:2px solid var(--color-divider)' : ''),
                )}
              >
                <div style={css('display:flex;align-items:center;gap:10px;margin-bottom:8px')}>
                  <span style={css(`width:10px;height:10px;flex:none;background:${s.live ? 'var(--color-accent)' : 'color-mix(in srgb,var(--color-text) 30%,transparent)'}`)} />
                  <span style={css('font-family:var(--font-heading);font-weight:800;font-size:17px')}>{s.title}</span>
                </div>
                <p style={css('font-size:14px;line-height:24px;color:color-mix(in srgb,var(--color-text) 78%,transparent);margin:0')}>{s.body}</p>
                <span className={s.live ? 'tag tag-accent' : 'tag tag-outline'} style={css('margin-top:12px')}>
                  {s.live ? 'Live today' : 'Next'}
                </span>
              </motion.div>
            ))}
          </motion.div>
        </section>

        <section style={css('padding:70px 0 98px')}>
          <motion.figure {...reveal} style={css('margin:0')}>
            <blockquote style={css('font-family:var(--font-heading);font-weight:800;font-size:clamp(24px,2.6vw,34px);line-height:42px;letter-spacing:-0.015em;max-width:34ch;margin:0;text-box:trim-both cap alphabetic')}>
              This is not construction software with AI features added on. It is a construction company designed around AI from the ground up.
            </blockquote>
            <figcaption style={css('font-size:15.5px;line-height:28px;color:color-mix(in srgb,var(--color-text) 70%,transparent);margin:42px 0 0;text-box:trim-both cap alphabetic')}>
              Software companies run on Linear and GitHub. The next generation of contractors will run on agents — and complete more work with the same team.
            </figcaption>
          </motion.figure>
        </section>

      </div>

      <section style={css('background:var(--color-accent);color:var(--color-bg)')}>
        <div style={css('max-width:1200px;margin:0 auto;padding:84px var(--edge)')}>
          <motion.h3 {...reveal} style={css('font-family:var(--font-heading);font-weight:800;font-size:clamp(34px,4.2vw,56px);line-height:clamp(36px,4.45vw,59.4px);letter-spacing:-0.015em;margin:0 0 0 -0.058em;text-box:trim-both cap alphabetic')}>
            <span style={css('display:block')}>The plan set is already on your desk.</span>
            <span style={css('display:block')}>Let the agents run the buy.</span>
          </motion.h3>
          <motion.div {...reveal} style={css('display:flex;gap:var(--space-3);flex-wrap:wrap;margin-top:42px')}>
            <Cta variant="ghost" style="color:var(--color-bg);border-color:var(--color-bg)">Book a demo</Cta>
            <Cta variant="ghost" style="color:var(--color-bg);border-color:var(--color-bg)">Talk to the founders</Cta>
          </motion.div>
        </div>
      </section>

      <div className="pq-shell">
        <footer style={css('padding:56px 0;font-size:13px;line-height:28px;color:color-mix(in srgb,var(--color-text) 70%,transparent);display:flex;gap:28px;flex-wrap:wrap;justify-content:space-between')}>
          <span>Proq — the operating system for AI-native general contractors.</span>
          <span>Procurement · Operations · Field</span>
        </footer>
      </div>

    </div>
  )
}
