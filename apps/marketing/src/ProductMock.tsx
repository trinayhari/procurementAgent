import { css, ICONS, Svg, SPARKLE, SPARKLE_SOLID, useFitToWidth } from './lib'
import type { ReactNode } from 'react'

// A pixel recreation of the Proq quote-comparison screen, authored at a fixed
// 1280px width and scaled to fit its frame. Everything here is presentational:
// the numbers are the Riverside water-utilities package the copy talks about.

type Supplier = { initials: string; name: string; meta: string; badge: string }
type Cell = { total: string; unit: string; best?: boolean }
type Line = { name: string; qty: string; cells: Cell[] }

const SUPPLIERS: Supplier[] = [
  { initials: 'FW', name: 'Ferguson Waterworks', meta: '21d · 18mi', badge: '#0a4d8c' },
  { initials: 'C&M', name: 'Core & Main', meta: '16d · 32mi', badge: '#16a34a' },
  { initials: 'FL', name: 'Fortiline Waterworks', meta: '26d · 47mi', badge: '#0f766e' },
]

const LINES: Line[] = [
  {
    name: '12" DI Pipe, Class 350', qty: '2,400 LF',
    cells: [
      { total: '$98,400', unit: '$41/unit · 14d', best: true },
      { total: '$100,320', unit: '$41.8/unit · 16d' },
      { total: '$103,200', unit: '$43/unit · 26d' },
    ],
  },
  {
    name: '12" Gate Valve, RW', qty: '8 EA',
    cells: [
      { total: '$15,200', unit: '$1900/unit · 14d' },
      { total: '$13,200', unit: '$1650/unit · 16d', best: true },
      { total: '$15,040', unit: '$1880/unit · 26d' },
    ],
  },
  {
    name: 'Fire Hydrant Assembly', qty: '6 EA',
    cells: [
      { total: '$18,900', unit: '$3150/unit · 21d', best: true },
      { total: '$20,400', unit: '$3400/unit · 16d' },
      { total: '$19,800', unit: '$3300/unit · 26d' },
    ],
  },
  {
    name: '12" MJ Tee', qty: '14 EA',
    cells: [
      { total: '$6,370', unit: '$455/unit · 14d' },
      { total: '$5,432', unit: '$388/unit · 16d', best: true },
      { total: '$6,580', unit: '$470/unit · 26d' },
    ],
  },
  {
    name: '12" 45° MJ Bend', qty: '22 EA',
    cells: [
      { total: '$5,016', unit: '$228/unit · 14d' },
      { total: '$4,620', unit: '$210/unit · 16d', best: true },
      { total: '$5,170', unit: '$235/unit · 26d' },
    ],
  },
]

const STRATEGIES = [
  { label: 'Lowest cost (mix & match)', total: '$143,852', meta: '21d lead · 2 suppliers · save $1,620', picked: true },
  { label: 'Fastest delivery', total: '$148,686', meta: '16d lead · 2 suppliers' },
  { label: 'Single supplier', total: '$145,472', meta: '16d lead · 1 supplier' },
]

const AWARD_ROWS = [
  ['Materials', '$140,552'],
  ['Freight (2 deliveries)', '$3,300'],
  ['Lead time', '21 days'],
  ['Suppliers', '2'],
  ['Max haul', '32 mi'],
]

const SIDEBAR = [
  { icon: ICONS.grid, label: 'Dashboard' },
  { icon: ICONS.folder, label: 'Projects', count: '5', active: true },
  { icon: ICONS.supplier, label: 'Suppliers' },
  { icon: ICONS.settings, label: 'Settings' },
]

const TABS = [
  { icon: ICONS.gridSm, label: 'Overview' },
  { icon: ICONS.file, label: 'Documents' },
  { icon: ICONS.supplier, label: 'Supplier Search' },
  { icon: ICONS.rfq, label: 'RFQs' },
  { icon: ICONS.quotes, label: 'Quotes', active: true },
  { icon: ICONS.timeline, label: 'Timeline' },
]

const ROW = 'display:grid;grid-template-columns:minmax(150px,1.4fr) repeat(3,minmax(116px,1fr));border-bottom:1px solid var(--border)'
const CELL = 'border-left:1px solid var(--border);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:10px 6px;position:relative'
const BEST_CELL = `${CELL};background:var(--primary-softer);box-shadow:inset 0 0 0 2px var(--primary)`

function Chip({ children, primary }: { children: ReactNode; primary?: boolean }) {
  return (
    <div
      style={css(
        `display:inline-flex;align-items:center;gap:7px;height:36px;padding:0 ${primary ? 14 : 13}px;border-radius:9px;font-size:13px;font-weight:600;` +
          (primary
            ? 'background:var(--primary);color:var(--on-primary);box-shadow:var(--shadow-sm)'
            : 'background:var(--panel);border:1px solid var(--border);color:var(--text)'),
      )}
    >
      {children}
    </div>
  )
}

export default function ProductMock() {
  const [frameRef, mockRef] = useFitToWidth()

  return (
    <div ref={frameRef} className="pq-frame" data-om-raster>
      <div ref={mockRef} className="pq-mock" style={css('display:flex;align-items:stretch;background:var(--bg)')}>

        <aside style={css('align-self:stretch;width:248px;flex:none;border-right:1px solid var(--border);background:var(--panel);display:flex;flex-direction:column;padding:16px 12px')}>
          <div style={css('padding:6px 8px 16px')}>
            <img src="/proq-lockup.png" alt="Proq" style={css('width:96px;height:auto;display:block')} />
          </div>
          <nav style={css('display:flex;flex-direction:column;gap:2px')}>
            {SIDEBAR.map((item) => (
              <div
                key={item.label}
                style={css(
                  'display:flex;align-items:center;gap:11px;width:100%;padding:8px 11px;border-radius:9px;font-size:13.5px;' +
                    (item.active
                      ? 'font-weight:600;color:var(--text);background:var(--panel-3)'
                      : 'font-weight:500;color:var(--text-2);background:transparent'),
                )}
              >
                <Svg d={item.icon} size={17} sw={1.9} />
                <span style={css('flex:1;text-align:left')}>{item.label}</span>
                {item.count && (
                  <span style={css('font-size:11px;font-weight:600;color:var(--text-3);background:var(--panel-3);padding:1px 7px;border-radius:999px')}>
                    {item.count}
                  </span>
                )}
              </div>
            ))}
          </nav>
          <div style={css('flex:1;min-height:40px')} />
          <div style={css('display:flex;align-items:center;gap:10px;margin-top:8px;padding:9px 8px;border-top:1px solid var(--border)')}>
            <div style={css('width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#7c3aed);color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex:none')}>JM</div>
            <div style={css('display:flex;flex-direction:column;line-height:1.2;min-width:0;flex:1')}>
              <span style={css('font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>Jordan Mills</span>
              <span style={css('font-size:11px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>Meridian Civil Co.</span>
            </div>
          </div>
        </aside>

        <div style={css('flex:1;min-width:0;display:flex;flex-direction:column')}>
          <header style={css('min-height:57px;display:flex;align-items:center;gap:12px;padding:0 26px;border-bottom:1px solid var(--border);background:var(--panel)')}>
            <div style={css('display:flex;align-items:center;gap:8px;min-width:0')}>
              <span style={css('font-size:14px;font-weight:500;color:var(--text-2);white-space:nowrap')}>Projects</span>
              <Svg d={ICONS.chevronRight} size={15} style={css('flex:none;color:var(--text-3)')} />
              <span style={css('font-size:14px;font-weight:600;white-space:nowrap')}>Riverside Water Treatment Plant</span>
            </div>
          </header>

          <div style={css('padding:22px 26px 26px')}>
            <div style={css('display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:18px')}>
              <div style={css('min-width:0')}>
                <h1 style={css('font-size:25px;font-weight:700;letter-spacing:-.02em')}>Riverside Water Treatment Plant</h1>
                <div style={css('display:flex;align-items:center;gap:18px;margin-top:7px;font-size:13px;color:var(--text-2);flex-wrap:wrap')}>
                  <span style={css('display:flex;align-items:center;gap:5px')}>
                    <Svg d={ICONS.pin} size={14} />
                    Sacramento, CA
                  </span>
                  <span>Value <strong className="pq-mono" style={css('color:var(--text)')}>$4.2M</strong></span>
                </div>
              </div>
              <div style={css('display:flex;gap:9px;flex-wrap:wrap')}>
                <Chip><Svg d={ICONS.upload} size={15} />Upload</Chip>
                <Chip primary><Svg d={SPARKLE} size={15} fill />Generate RFQs</Chip>
              </div>
            </div>

            <div style={css('display:flex;border-bottom:1px solid var(--border);margin-bottom:22px;overflow-x:auto;overflow-y:hidden')}>
              {TABS.map((tab) => (
                <div
                  key={tab.label}
                  style={css(
                    'display:inline-flex;align-items:center;gap:7px;padding:13px 2px;margin-right:20px;font-size:13.5px;margin-bottom:-1px;white-space:nowrap;' +
                      (tab.active
                        ? 'font-weight:600;color:var(--text);border-bottom:2px solid var(--primary)'
                        : 'font-weight:500;color:var(--text-2);border-bottom:2px solid transparent'),
                  )}
                >
                  <Svg d={tab.icon} size={15} sw={1.9} />{tab.label}
                </div>
              ))}
            </div>

            <div style={css('display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:500;color:var(--text-2);margin-bottom:14px')}>
              <Svg d={ICONS.chevronLeft} size={16} />Back to quotes
            </div>
            <div style={css('margin-bottom:16px')}>
              <h2 style={css('font-size:19px;font-weight:700;letter-spacing:-.02em')}>Water Utilities — Quote Comparison</h2>
              <p style={css('margin:4px 0 0;font-size:13px;color:var(--text-2)')}>3 suppliers · 5 line items · budget $165,000</p>
            </div>

            <div style={css('display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px')}>
              {STRATEGIES.map((s) => (
                <div
                  key={s.label}
                  style={css(
                    'flex:1;min-width:150px;text-align:left;padding:11px 13px;border-radius:12px;' +
                      (s.picked
                        ? 'border:2px solid var(--primary);background:var(--primary-softer)'
                        : 'border:1px solid var(--border);background:var(--panel)'),
                  )}
                >
                  <div style={css('display:flex;align-items:center;gap:6px;font-size:12.5px;font-weight:700')}>
                    {s.picked && <Svg d={SPARKLE_SOLID} size={14} fill style={css('color:var(--primary)')} />}
                    {s.label}
                  </div>
                  <div className="pq-mono" style={css('font-size:15px;font-weight:700;margin-top:4px')}>{s.total}</div>
                  <div style={css('font-size:11px;color:var(--text-3);margin-top:2px')}>{s.meta}</div>
                </div>
              ))}
            </div>

            <div style={css('display:grid;grid-template-columns:minmax(0,1.7fr) 320px;gap:16px;align-items:start')}>
              <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);overflow:hidden')}>
                <div style={css('overflow-x:auto;overflow-y:hidden')}><div style={css('min-width:560px')}>

                  <div style={css(ROW)}>
                    <div style={css('padding:14px 16px;display:flex;align-items:flex-end;font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--text-3);text-transform:uppercase')}>Line item</div>
                    {SUPPLIERS.map((sup) => (
                      <div key={sup.initials} style={css('padding:12px 8px;display:flex;flex-direction:column;align-items:center;gap:5px;text-align:center;border-left:1px solid var(--border)')}>
                        <div style={css(`width:30px;height:30px;border-radius:8px;background:${sup.badge};color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:11px;flex:none;letter-spacing:-.02em`)}>
                          {sup.initials}
                        </div>
                        <div style={css('font-size:11.5px;font-weight:600;line-height:1.15')}>{sup.name}</div>
                        <div style={css('font-size:10px;color:var(--text-3)')}>{sup.meta}</div>
                      </div>
                    ))}
                  </div>

                  {LINES.map((line) => (
                    <div key={line.name} style={css(ROW)}>
                      <div style={css('padding:12px 16px;display:flex;flex-direction:column;justify-content:center;gap:2px')}>
                        <span style={css('font-size:12.5px;font-weight:600;line-height:1.25')}>{line.name}</span>
                        <span style={css('font-size:11px;color:var(--text-3)')}>{line.qty}</span>
                      </div>
                      {line.cells.map((cell, i) => (
                        <div key={SUPPLIERS[i].initials} style={css(cell.best ? BEST_CELL : `${CELL};background:transparent`)}>
                          {cell.best && (
                            <span style={css('position:absolute;top:5px;right:6px;display:inline-flex;align-items:center;gap:2px;font-size:9px;font-weight:700;color:var(--success)')}>
                              <Svg d={ICONS.check} size={10} sw={3} />Best
                            </span>
                          )}
                          <span
                            className="pq-mono"
                            style={css(`font-size:13.5px;${cell.best ? 'font-weight:700;color:var(--success)' : 'font-weight:500;color:var(--text)'}`)}
                          >
                            {cell.total}
                          </span>
                          <span style={css('font-size:10px;color:var(--text-3)')}>{cell.unit}</span>
                        </div>
                      ))}
                    </div>
                  ))}

                </div></div>
              </div>

              <div style={css('display:flex;flex-direction:column;gap:14px')}>
                <div style={css('background:var(--primary-softer);border:1px solid var(--primary-soft);border-radius:16px;padding:18px;box-shadow:var(--shadow-md)')}>
                  <div style={css('display:flex;align-items:center;gap:8px;margin-bottom:14px')}>
                    <span style={css('width:28px;height:28px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center')}>
                      <Svg d={SPARKLE_SOLID} size={16} fill />
                    </span>
                    <span style={css('font-size:13px;font-weight:700;color:var(--primary)')}>Award plan</span>
                  </div>
                  <div style={css('font-size:11px;color:var(--text-3)')}>Total committed</div>
                  <div className="pq-mono" style={css('font-size:24px;font-weight:700;line-height:1.1')}>$143,852</div>
                  <div style={css('margin-top:8px')}>
                    <div style={css('height:6px;border-radius:999px;background:var(--panel-3);overflow:hidden')}>
                      <div style={css('width:87.2%;height:100%;background:var(--success)')} />
                    </div>
                    <div style={css('font-size:11px;margin-top:3px;color:var(--text-3)')}>$21,148 under budget</div>
                  </div>
                  <div style={css('display:flex;flex-direction:column;gap:7px;margin:14px 0;font-size:12.5px')}>
                    {AWARD_ROWS.map(([label, value]) => (
                      <div key={label} style={css('display:flex;justify-content:space-between')}>
                        <span style={css('color:var(--text-2)')}>{label}</span>
                        <span className="pq-mono">{value}</span>
                      </div>
                    ))}
                  </div>
                  <div style={css('font-size:12px;color:var(--success);background:var(--success-soft);border-radius:9px;padding:9px 11px;margin-bottom:10px;line-height:1.4')}>
                    Saves $1,620 vs. the best single supplier.
                  </div>
                  <div style={css('width:100%;height:38px;border-radius:9px;background:var(--primary);color:#fff;font-size:13px;font-weight:600;display:flex;align-items:center;justify-content:center')}>
                    Submit award · issue 2 POs
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
