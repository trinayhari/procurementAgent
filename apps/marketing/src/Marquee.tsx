// Two rows of the questions a PE fields all week, scrolling in opposite
// directions. The visual rows are aria-hidden; a plain list carries the text
// for assistive tech. Motion is CSS-only and switched off by
// prefers-reduced-motion (see index.css), where the rows render as a wrapped
// static list instead.

const QUOTES = [
  'Did the steel quote come in?',
  'Who’s chasing the rebar lead time?',
  'Is that price still good?',
  'Which addendum is this BOM on?',
  'Has the supplier confirmed delivery?',
  'Did anyone level the three bids?',
  'Who owns the PO?',
  'Does this push the pour?',
]

function Row({ items, reverse }: { items: string[]; reverse?: boolean }) {
  // The track holds the list twice so the -50% translate loops seamlessly.
  const doubled = [...items, ...items]
  return (
    <div className={`marquee${reverse ? ' marquee--reverse' : ''}`} aria-hidden="true">
      <div className="marquee__track">
        {doubled.map((q, i) => (
          <span key={i} className="marquee__item">{q}</span>
        ))}
      </div>
    </div>
  )
}

export default function Marquee() {
  const half = Math.ceil(QUOTES.length / 2)
  return (
    <>
      <ul className="sr-only">
        {QUOTES.map((q) => <li key={q}>{q}</li>)}
      </ul>
      <Row items={QUOTES.slice(0, half).concat(QUOTES.slice(half))} />
      <Row items={QUOTES.slice(half).concat(QUOTES.slice(0, half))} reverse />
    </>
  )
}
