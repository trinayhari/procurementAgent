# Current-State Review — ProcureAI / gcOS

Date: 2026-07-16. Baseline: `main` @ `f54bcf3`.

This review compares the existing repository against the production requirements
in [design.md](../design.md). It covers what exists, what is real vs. mocked,
and what must be fixed or built to make the product production-ready.

---

## 1. Executive summary

The repo is a **working single-tenant demo with a surprisingly complete happy
path** — not a visual-only prototype, but far from production. The full
procurement flow (upload plans → AI BOM extraction → supplier discovery →
supplier selection → RFQ generation → Gmail send → quote ingestion → line-level
comparison → award) is wired end-to-end through real API mutations, with every
external dependency (OpenAI, Google Places, Gmail) cleanly degrading to a
deterministic mock when unconfigured.

What it lacks is essentially **everything in the "production" column** of
design.md:

- **No authorization**: only 3 of ~40 routes require a user; nothing is scoped
  to a user or organization. There is no organization/tenant concept at all.
- **No tests** — zero backend or frontend test files despite pytest/Playwright
  being configured. CI only smoke-checks imports and type-checks.
- **No durability**: background work is in-process `BackgroundTasks` with
  module-level in-memory status dicts; no queue, no outbox, no retries, no
  exception queue. Breaks under multi-worker deploys and restarts.
- **No idempotency or approval gating on RFQ send** — re-POSTing the send
  endpoint re-emails every supplier.
- **No state machine enforcement** — statuses are free strings set directly.
- **Weak data model** vs. design.md: no ProcurementPackage entity (packages are
  hardcoded presets), RFQ recipients are a JSON blob not a table, no audit
  trail, no provenance records, no versioning, integer-ish demo IDs rather than
  UUIDs in places.
- **Storage**: local-disk uploads + SQLite default; both ephemeral on the
  current Railway/Render deploy. No object storage, no signed URLs, no
  checksums, no versioning.
- **Secret hygiene problems**: live OpenRouter key, Google Maps key, and a
  Gmail OAuth **refresh token** sit in `backend/.env` in the working tree
  (gitignored but real — rotate them); default JWT secret is
  `"dev-insecure-change-me"` with no startup guard; a demo account
  `jordan@meridiancivil.com` / `procureai` is seeded unconditionally in every
  environment.

**Recommendation**: keep the frontend, the extraction pipeline, the discovery/
relevance/comparison engines, and the provider-fallback philosophy. Rebuild the
domain layer around real entities (Organization, ProcurementPackage,
RFQRecipient, AuditEvent…), add auth/tenancy everywhere, replace in-memory
background state with a durable job/outbox pattern, and build the test suite.

---

## 2. What exists and genuinely works

### 2.1 Frontend (React + Vite + TS, `src/`)
- Single-page app, hash-routed, gated behind JWT login ([App.tsx:307](../src/App.tsx)).
- **Every major flow is wired to real API mutations** — this is not a mock UI:
  - Project create/delete, document upload (multipart), manual/custom BOM.
  - BOM review: inline line-item editing (`PUT /line-items`), Confirm BOM
    (`POST /confirm`) — human-in-the-loop exists ([App.tsx:1134](../src/App.tsx)).
  - Supplier search kickoff + polling, candidate multi-select, add-to-network.
  - RFQ generate, draft edit, review modal with recipient editing, send.
  - Quote ingest + polling, quotes table, line-level comparison with three
    award strategies and split-award submit ([App.tsx:1883](../src/App.tsx)).
  - Timeline milestones with done/overdue tracking.
- Type-safe client: `src/api-types.ts` generated from the backend OpenAPI
  schema; CI fails on drift.
- Empty-state driven — `model.ts` falls back to empty arrays, not fake data
  (one dead hardcoded RFQ `thread` literal at [model.ts:296](../src/model.ts) and unused
  `selectQuote` at [api.ts:372](../src/api.ts)).

### 2.2 Document upload + BOM extraction (`backend/app/services/extraction/`)
The strongest backend subsystem:
- Text-first extraction (read PDF text layer; vision tiling fallback for
  scans/CAD), CAD text dedup, per-sheet parallel vision with a consolidation
  pass, vision top-up for graphical categories.
- Runs in a **subprocess** with timeout to isolate PyMuPDF segfaults
  ([isolated.py](../backend/app/services/extraction/isolated.py)) — deliberate, battle-tested design.
- OpenAI Structured Outputs (`gpt-4.1`), `temperature=0`; clearly-flagged mock
  extraction when no key.
- Per-item provenance: source sheet, confidence, spec, assumptions.
- Orphaned-processing recovery on boot; upload rehydration from disk.

### 2.3 Supplier discovery (`backend/app/services/sourcing/`)
- Google Geocoding + Places Text Search + Place Details over httpx, keyword
  fan-out per package, dedupe by `place_id`, haversine prefilter, concurrent
  enrichment (website fetch, email discovery, relevance scoring).
- Relevance = heuristic term lists blended with optional LLM verification
  (0.35/0.65), thresholded — **not purely LLM-ranked**, which matches the
  design principle.
- Deterministic mock supplier lists when no Maps key.

### 2.4 RFQ + quotes (`backend/app/services/rfq/`, `quotes/`)
- RFQ draft: templated body, optional LLM polish; line items come from
  structured extracted data, not LLM invention. Recipients capped at 10.
- Email: the codebase's one true provider abstraction — `EmailSender` Protocol
  with `GmailSender` (OAuth refresh token, `gmail.send` scope only) and
  `MockSender` ([sender.py:41](../backend/app/services/rfq/sender.py)).
- Quote ingest: Gmail reply fetch (separate `gmail.readonly` module), PDF
  attachment text extraction, OpenAI Structured Outputs parse with regex
  fallback; dedup by Gmail message id (ingest *is* idempotent).
- Comparison: weighted recommendation (0.6 cost / 0.3 lead / 0.1 risk) plus a
  line-level engine with brute-force optimal mix, fastest, and single-supplier
  award strategies ([line_comparison.py:63](../backend/app/services/quotes/line_comparison.py)).
  Deterministic, not LLM-ranked.

### 2.5 Tooling / deploy scaffolding
- Alembic with 12 migrations; Railway/Render start commands run
  `alembic upgrade head`.
- CI (GitHub Actions): frontend typecheck+build, backend import + migration
  smoke test against throwaway SQLite, OpenAPI-drift check; CD to Vercel
  (frontend) and Railway (backend).
- `docker-compose.yml` for local Postgres. Health endpoint `/health`.

---

## 3. Critical gaps (must fix)

### 3.1 Security & tenancy — the biggest gap
| Issue | Location | Severity |
|---|---|---|
| ~40 routes unauthenticated (documents, projects, quotes, RFQs, suppliers, dashboard, award) — anyone can read/delete/award anything by id | all route files; only `auth.me`, `auth.update_me`, `sourcing.send_generated_rfq` check a user | Critical |
| No organizations/tenants; `Project` has no owner column; queries never scoped to caller | [models/project.py](../backend/app/models/project.py), [models/user.py](../backend/app/models/user.py) | Critical |
| Demo account `jordan@meridiancivil.com`/`procureai` seeded unconditionally in every deploy | [repositories/users.py:68](../backend/app/repositories/users.py), [db.py:55](../backend/app/db.py) | Critical |
| Default JWT secret `dev-insecure-change-me`, no startup guard | [config.py:34](../backend/app/config.py) | Critical |
| Live secrets in working-tree `backend/.env` (OpenRouter key, Maps key, **Gmail refresh token**) — rotate all | `backend/.env` | Critical (operational) |
| Uploads collide by filename (`uploads/<name>`, no namespacing); no extension allowlist; direct unauthenticated file download route | [documents.py:184](../backend/app/api/routes/documents.py) | High |
| No rate limiting, no roles/permissions, no trusted-host, 7-day tokens, no revocation | — | High |
| CORS hardcoded to localhost origins with credentials on | [config.py:13](../backend/app/config.py), [main.py:42](../backend/app/main.py) | Medium |

### 3.2 Reliability & durability
| Issue | Location | Severity |
|---|---|---|
| Supplier-search and quote-ingest status in **module-level dicts** — lost on restart, wrong under >1 worker | [sourcing.py:46,49](../backend/app/api/routes/sourcing.py) | Critical |
| **RFQ send has no idempotency, no status precondition, no duplicate-send guard** — re-POST re-emails all suppliers | [sourcing.py:460](../backend/app/api/routes/sourcing.py) | Critical |
| No retry for failed sends — failure stored as `sentMessageId="error: ..."` string | [sourcing.py:483](../backend/app/api/routes/sourcing.py) | High |
| No approval workflow before send (design requires user approval of first outbound RFQ) | — | High |
| No outbox, no durable job queue, no scheduler, no follow-up automation at all | — | High |
| No exception queue / dead-letter surface for failed jobs | — | High |
| Status strings with **no state-machine enforcement** (Draft→Sent→Awaiting→Quoted set freely) | [models/rfq.py:32](../backend/app/models/rfq.py), repos | High |
| Bare `except Exception` swallowing on all LLM/HTTP paths — silent failures, no logging/metrics | relevance, emails, generator, parser | Medium |
| `init_db()` runs `create_all` + manual `ALTER TABLE`s alongside Alembic — schema drift (already bit us locally) | [db.py:35,71](../backend/app/db.py) | Medium |
| No optimistic locking / row versions anywhere | — | Medium |

### 3.3 Data model vs. design.md
- **No ProcurementPackage entity** — packages are a hardcoded 15-category
  preset dict ([packages.py:19](../backend/app/services/sourcing/packages.py)); no CRUD, no per-package delivery
  dates/addresses/qualification rules/status.
- **RFQ recipients are a JSON array on the Rfq row**, not an `RFQRecipient`
  table — no per-recipient delivery status, follow-up count, or failure reason.
- **No BOM-item approval gate for packages** — package line items are pulled
  live from extracted docs; unconfirmed items aren't excluded.
- **FoundSupplier is a wholesale delete+insert cache** per (project, package) —
  no candidate decisions, no match-reason preservation across searches.
- Missing entirely: Organization, ProjectMember, DocumentVersion,
  ExtractionRun (as an entity), BOMItem/BOMItemRevision (BOM lives as a JSON
  blob on Document), SupplierCandidateDecision, RFQVersion, RFQRecipient,
  Communication (SupplierComm is a shared display list), FollowUpPolicy/
  Execution, QuoteVersion/QuoteException, Recommendation (computed on the fly,
  never stored), PurchaseDecision (award = status flip, no record of decision
  maker/reason/deviation), ApprovalRequest, AuditEvent, OutboxEvent,
  BackgroundJob.
- `project_events` is a UI activity feed, not an audit trail (no actor, not
  append-only-guaranteed, incomplete coverage).

### 3.4 Storage
- Local-disk uploads (`uploads/`), **ephemeral** on Railway/Render — documents
  vanish on redeploy (known follow-up). No object storage, no SHA-256
  checksums, no versioning, no signed URLs, no tenant-scoped keys.
- Default SQLite DB; a stale `backend/procureai.db` (258 KB) and an empty root
  `procureai.db` are **committed to git** and should be removed.

### 3.5 Testing & CI
- **Zero test files** (backend or frontend) despite `pyproject.toml`
  configuring pytest and Playwright being a devDependency.
- CI runs no behavioral tests; deploys are gated only on typecheck/build/
  import/migration smoke.
- None of design.md's 28 required test cases exist; no tenant-isolation or
  idempotency tests (nothing to test yet — there's no tenancy/idempotency).

### 3.6 Known stubs & partial implementations
- `POST /api/rfqs/{id}/messages` and `/followup` are stubs operating on demo
  reference RFQs, not real ones ([rfqs.py:34](../backend/app/api/routes/rfqs.py)).
- Mock quotes carry no line items → line comparison silently empty on the mock
  path ([ingest.py:87](../backend/app/services/quotes/ingest.py)).
- `_recipient_index` maps first-RFQ-per-email — a supplier on two package RFQs
  only ingests against one ([ingest.py:26](../backend/app/services/quotes/ingest.py)).
- Places Text Search reads only page 1 of results ([places.py:63](../backend/app/services/sourcing/places.py));
  distances are haversine, not driving.
- Award/"issue PO" is a status flip + event string — no PO/PurchaseDecision
  record ([projects.py:174](../backend/app/api/routes/projects.py)).
- Supplier discovery has no provider Protocol (Google hard-referenced; mock is
  an if-branch) — email sending is the only real provider abstraction.
- No supplier response classification (QUOTE_ATTACHED/DECLINED/…), no
  communication records, no follow-up automation.
- No observability: no structured logging, metrics, tracing, or correlation IDs.

### 3.7 Deployment & DX
- Docs lead with Render (`render.yaml`) but CI/CD actually deploys to Railway —
  ambiguous target.
- Python drift: local `.venv` is 3.8, prod pins 3.11.9 (recurring compat fixes).
- No Dockerfiles (buildpack/Nixpacks only). No readiness endpoint beyond
  `/health`. No env validation at startup. No backup/restore/rollback docs.
- Committed junk: `.DS_Store` files, `backend/procureai.db`, root `procureai.db`.

---

## 4. Reuse vs. replace

**Keep (solid foundations):**
- Frontend app + generated-types pipeline (add auth-scoped fetching later).
- Extraction pipeline wholesale (subprocess isolation, text-first, provenance).
- Discovery enrichment/relevance engine and comparison/award engines (wrap them
  behind provider interfaces and real entities).
- `EmailSender` Protocol pattern — extend it, and replicate it for discovery.
- Alembic setup, docker-compose, CI drift-check.

**Replace / build new:**
- Domain layer: real entities (Organization, ProcurementPackage,
  RFQRecipient, AuditEvent, PurchaseDecision, OutboxEvent, BackgroundJob…),
  UUIDs, org scoping, row versions, enforced state machines in services.
- Auth layer: org membership + roles, `Depends` chain on every router,
  tenant-scoped queries, signed file URLs.
- Background execution: durable job table + worker (or workflow engine),
  outbox pattern, retries with backoff, exception queue.
- Storage: S3-compatible abstraction (MinIO locally), checksums, versioning.
- Test suite: pytest (unit/service/API/tenant-isolation/idempotency),
  Playwright E2E of the full flow on fake providers.
- Observability: structured logging + correlation IDs, basic metrics.

---

## 5. Suggested fix order (feeds the implementation plan)

1. **Stop the bleeding**: rotate leaked credentials; remove committed DBs and
   `.DS_Store`; JWT-secret startup guard; gate demo-user seeding behind env.
2. **Auth everywhere**: require auth on every router; add Organization +
   membership + roles; scope every query; migrate data model to org-owned.
3. **Real domain entities**: ProcurementPackage (CRUD + status machine),
   RFQRecipient table, PurchaseDecision, AuditEvent (append-only), BOM approval
   gate feeding packages.
4. **Reliability**: durable BackgroundJob + outbox tables replacing in-memory
   dicts; idempotent RFQ send with status preconditions and per-recipient
   idempotency keys; retries; exception queue API + UI.
5. **Storage**: object-storage abstraction, checksums, signed URLs.
6. **Provider interfaces**: `SupplierDiscoveryProvider` Protocol (db/google/
   fake), keep `EmailSender`, add fake LLM provider for tests.
7. **Tests**: backend suite covering design.md's 28 cases, then Playwright E2E
   on fake providers; wire into CI as a deploy gate.
8. **Observability + deploy hardening**: structured logs, correlation IDs,
   Dockerfiles, env validation, readiness, single documented deploy target.
