import { css, ICONS, Svg } from './lib'
import { motion, staggerParent, staggerItem } from './motion'

// The product's "Recent activity" panel — the visible trace of agent work that
// happened without anyone opening a tab.

type Tone = 'success' | 'primary'
type Event = { icon: string; tone: Tone; title: string; context: string; age: string }

const EVENTS: Event[] = [
  { icon: ICONS.quote, tone: 'success', title: 'Quote received from Ferguson', context: 'Water Utilities · Riverside WTP', age: '12m' },
  { icon: ICONS.quote, tone: 'success', title: 'Quote received from Core & Main', context: 'Water Utilities · Riverside WTP', age: '35m' },
  { icon: ICONS.sparkles, tone: 'primary', title: 'AI found $1,620 split-award saving', context: 'Water Utilities · Riverside WTP', age: '40m' },
  { icon: ICONS.quote, tone: 'success', title: 'Quote received from HD Supply', context: 'Sanitary Sewer · Riverside WTP', age: '2h' },
  { icon: ICONS.truck, tone: 'primary', title: 'Delivery schedule updated', context: 'Storm Drain · Eastgate', age: '5h' },
  { icon: ICONS.sparkles, tone: 'primary', title: 'AI extracted 142 line items', context: 'Civil Site Plan Rev 3 · Riverside', age: '1d' },
]

export default function ActivityFeed() {
  return (
    <div data-om-raster style={css('border:2px solid var(--color-text);background:#ffffff')}>
      <div className="pq-mock" style={css('background:var(--panel);overflow:hidden')}>
        <div style={css('display:flex;align-items:center;justify-content:space-between;padding:15px 18px;border-bottom:1px solid var(--border)')}>
          <h2 style={css('font-size:15px;font-weight:600')}>Recent activity</h2>
          <span style={css('width:7px;height:7px;border-radius:50%;background:var(--success);box-shadow:0 0 0 3px var(--success-soft)')} />
        </div>
        <motion.div {...staggerParent} style={css('padding:6px 8px')}>
          {EVENTS.map((e) => (
            <motion.div key={e.title} variants={staggerItem} style={css('display:flex;gap:11px;padding:10px;border-radius:10px')}>
              <div
                style={css(
                  `width:30px;height:30px;border-radius:9px;flex:none;display:flex;align-items:center;justify-content:center;background:var(--${e.tone}-soft);color:var(--${e.tone})`,
                )}
              >
                <Svg d={e.icon} size={15} />
              </div>
              <div style={css('flex:1;min-width:0')}>
                <div style={css('font-size:13px;font-weight:500;line-height:1.35')}>{e.title}</div>
                <div style={css('font-size:11.5px;color:var(--text-3);margin-top:1px')}>{e.context}</div>
              </div>
              <span style={css('font-size:11px;color:var(--text-3);white-space:nowrap')}>{e.age}</span>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </div>
  )
}
