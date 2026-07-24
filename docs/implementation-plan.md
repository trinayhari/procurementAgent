# Implementation Plan — Production Hardening

Branch: `production-hardening`. Scope adjusted per product decision:
**no organizations/multi-tenancy yet** — the app remains a single shared
workspace, but every route requires an authenticated user and consequential
actions record *who* did them. Everything else from
[current-state-review.md](current-state-review.md) §5 proceeds.

## Milestones

### M1 — Security hardening
- Require a valid JWT on **every** API route except `/health`,
  `POST /api/auth/login`, `POST /api/auth/register` (router-level dependency
  at include time in `main.py`).
- Startup guard: refuse to boot with the default JWT secret unless
  `PROCUREAI_ENV=development` (new setting, default `development`; Render/
  Railway set `production`).
- Demo user seeding moves behind `seed_demo_data` (no more unconditional
  backdoor account).
- Upload safety: store files under a per-document unique name
  (`{uuid}_{basename}`), extension allowlist (pdf/csv/xlsx/xls/png/jpg),
  keep original filename as display name.
- Simple in-app rate limit on login/register (per-IP sliding window; no new
  dependency).
- CORS origins must be set explicitly in production (guard alongside JWT).

### M2 — Reliability
- New `background_jobs` table (id, kind, ref key, status, detail JSON,
  error, attempts, created/updated) replacing the in-memory
  `_SEARCH_STATUS` / `_INGEST_STATUS` dicts — job state survives restarts
  and works under multiple workers.
- RFQ **state machine** enforced in a service: `Draft → Sent → Awaiting →
  Quoted` (+ `Draft → Deleted`); illegal transitions raise 409.
- Idempotent send: precondition RFQ is sendable; per-recipient skip when a
  `sentMessageId` already exists; failures recorded per-recipient with a
  `POST .../rfqs/{id}/send` retry semantics (re-send only failed/unsent
  recipients — never re-emails a delivered one).
- Failed jobs queryable via `GET /api/jobs?status=failed` (operator
  exception queue).

### M3 — Domain integrity
- **BOM approval gate**: package line items (and RFQ generation) only draw
  from documents whose extraction was human-confirmed (`reviewed=True`);
  unreviewed docs are surfaced as "pending review" instead of silently
  included.
- **Audit trail**: append-only `audit_events` (id, actor user id + email,
  action, entity type/id, project id, detail JSON, created_at). Written for:
  document upload/confirm/delete, BOM edits, supplier search, RFQ
  generate/edit/send/delete, quote ingest, award, milestone check-off,
  auth events (login/register). Read-only `GET /api/audit` endpoint.
- **Purchase decisions**: `purchase_decisions` table recording award
  (project, package, strategy, selections, totals, decision maker,
  timestamp, note). Award route writes it atomically with the status flips.

### M4 — Frontend
- Central fetch wrapper attaches `Authorization: Bearer` to every call;
  401 → clear token, return to login.
- Regenerate `apps/web/src/api-types.ts`; surface duplicate-send / not-sendable
  errors in the RFQ modal.

### M5 — Tests + CI
- Pytest + httpx TestClient against a temp SQLite DB, fake providers
  (mock sender / no keys) — no network.
- Coverage: auth wall on every router, register/login flows, rate limit,
  BOM gate, RFQ transition matrix, duplicate-send prevention, partial-fail
  retry, job persistence, audit coverage of the full flow, award record.
- CI: `pytest` becomes a required job before deploy.

### M6 — Docs + deploy
- README/DEPLOYMENT updated: env-var reference (incl. `PROCUREAI_ENV`),
  single documented deploy story, migration + seed commands, known
  limitations (single workspace/no orgs; uploads on local disk — object
  storage is the next milestone; no follow-up automation yet).

## Deliberately deferred (documented as limitations)
- Organizations / multi-tenancy (product decision — "not yet").
- Object storage (S3/MinIO) + signed URLs — uploads remain local-disk.
- Durable worker/queue beyond DB-tracked jobs (Celery/Temporal later).
- Follow-up automation, supplier response classification.
- RFQRecipient as a first-class table (kept as JSON on `Rfq` for API
  compatibility; per-recipient send state is tracked inside it).

## Migration strategy
- New Alembic migrations: `0013_background_jobs`, `0014_audit_events`,
  `0015_purchase_decisions`. Local dev DBs may need
  `alembic stamp 0012` before `upgrade head` (create_all drift).

## Acceptance criteria
- Backend boots locally; refuses to boot in production mode with default
  secret; all non-auth routes return 401 without a token.
- Sending an RFQ twice does not re-email any recipient (test-proven).
- Search/ingest status survives a process restart.
- Award writes a purchase decision + audit event.
- Full pytest suite green in CI; frontend typecheck + build green.
