# @proq/marketing

The public Proq landing page. A standalone Vite + React app — it shares nothing
with `@proq/web` at runtime and talks to no backend.

```bash
npm run dev:marketing     # from the repo root, http://localhost:5174
npm run build --workspace @proq/marketing
```

## Where the design comes from

Ported from the Claude Design project *AI procurement for contractors*
(`Proq Landing.dc.html`). Two pieces of that project are reproduced here:

- **`src/ds.css`** — the Modernist design system, vendored from
  `_ds/modernist-…/styles.css`. Treat it as generated: retune it in the design
  project and re-copy, so the two don't drift. The only local change is that the
  Archivo `@import` is dropped in favour of loading it from `index.html`.
- **`src/index.css`** — page-level styles, including the product-mock palette.
  That palette is the *product's* (`apps/web/src/index.css`), not Modernist's:
  the embedded screenshots deliberately look like the app rather than the
  marketing chrome.

The design's `<sc-if>` switches survive as props on `<Landing>`:
`altHeadline`, `showProductScreen`, `showAgentFeed`.

Three responsive rules go beyond the source design, each marked with a
`Beyond the design:` comment — the source has no mobile handling for the nav row
or the "Always running" split.

## Configuration

| Variable         | Effect |
| ---------------- | ------ |
| `VITE_DEMO_URL`  | Destination for "Book a demo" / "Talk to the founders". Unset, those render as the inert buttons the design specifies rather than a guessed address. |

## Deployment

Live at <https://tryproq.dev> (`www` 308-redirects to the apex) as the Vercel
project `proq-marketing`. That's a second project on this repo: the root
`vercel.json` belongs to the `procureai` project, which builds `@proq/web` and
serves <https://app.tryproq.dev>. This directory is linked to `proq-marketing`
(`.vercel/`), so run `vercel` commands for the marketing site from
`apps/marketing`. DNS is managed at GoDaddy; both hosts CNAME/A to Vercel.
