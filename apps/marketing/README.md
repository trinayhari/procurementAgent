# @proq/marketing

The public Proq landing page. A standalone Vite + React app; it shares nothing
with `@proq/web` at runtime and talks to no backend.

```bash
npm run dev:marketing     # from the repo root, http://localhost:5174
npm run build --workspace @proq/marketing
```

## Where the design comes from

The page positions Proq as **Procurement-as-a-Service**: we run the buy for
general contractors, agents do the work, the GC approves every award. The
visual system is modelled on the current crop of services-style AI landing
pages (near-black canvas, one accent, alternating black / off-white bands,
tight geometric type, square controls, mono micro-labels): structure and
rhythm only; copy, nouns and mocks are Proq's.

- **`src/index.css`**: the whole stylesheet. Tokens live on `:root`; each
  `.band--dark` / `.band--light` sets the same four local tokens (`--bg`,
  `--fg`, `--fg-2`, `--line`) so every component is theme-agnostic. Type is
  Inter Tight at weight 500 with tight tracking; IBM Plex Mono carries the
  uppercase labels. Both load from Google Fonts in `index.html`.
- **`src/Landing.tsx`**: section order and copy: hero → the pain (marquee +
  proof strip) → what we do → the flow → what's in a buyout → who it's for +
  how we charge → footer CTA.
- **`src/Flow.tsx`**: the centrepiece: four auto-advancing, clickable,
  keyboard-navigable steps (5s each; paused on hover, off under
  `prefers-reduced-motion`) over an "illustrative example" panel that mocks
  the real work: inbox card, connected BOM / packages / suppliers / award
  cards with a measured connector tree, then a chat thread where the award is
  approved in one reply.
- **`src/HeroField.tsx`**: the hero background: a canvas dot field with a slow
  diagonal sweep. No image or video assets.
- **`src/Marquee.tsx`**: the two counter-scrolling rows of PE questions.

## Configuration

| Variable         | Effect |
| ---------------- | ------ |
| `VITE_DEMO_URL`  | Destination for "Request a buyout" / "Talk to us" / "Start a conversation". Unset, those render as inert buttons rather than a guessed address. |

## Deployment

Not wired up. The repo's `vercel.json` builds `@proq/web` only; shipping this
page means a second Vercel project pointed at the same repo with
`buildCommand: npm run build --workspace @proq/marketing` and
`outputDirectory: apps/marketing/dist`.
