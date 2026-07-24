# Reliability & Security Review — production-hardening branch

Date: 2026-07-16. Scope: the state of the app after milestones M1–M5
(see [implementation-plan.md](implementation-plan.md)). Each area lists what
is now enforced (with the test that proves it) and what remains open.

## Authorization & tenancy
- ✅ Every API route requires a valid JWT except `/health`, login, register,
  and the signed file URL (scoped-token gated). Proven by
  `test_every_route_requires_auth`, which walks the live route table.
- ✅ Signed file tokens are single-document scoped and rejected as API bearer
  tokens (`test_file_route_rejects_missing_and_foreign_tokens`,
  `test_scoped_token_is_not_an_api_token`).
- ✅ No demo backdoor account unless `PROCUREAI_SEED_DEMO_DATA=true`
  (`test_demo_account_not_seeded`).
- ✅ Login/register rate-limited per IP (`test_login_rate_limit`) — note the
  limiter is per-process; behind N workers the effective limit is N×.
- ⚠️ **Open (by product decision):** no organizations/multi-tenancy — all
  authenticated users share one workspace and can see each other's projects.
  No roles/permissions. Revisit before onboarding multiple companies.

## Configuration safety
- ✅ `PROCUREAI_ENV=production` refuses to boot with the default JWT secret
  (CI verifies this) and warns when CORS is localhost-only.
- ✅ `render.yaml` sets production mode + a generated secret.
- ⚠️ Local `apps/api/.env` previously held live credentials that were exercised
  during development; they should be **rotated** (OpenRouter key, Google Maps
  key, and especially the Gmail refresh token).

## Duplicate sends & idempotency
- ✅ RFQ send requires status Draft/'Send failed' (409 otherwise) and skips
  recipients that already have a successful send — a supplier is never
  emailed twice (`test_send_is_duplicate_safe`,
  `test_partial_failure_and_retry_only_failed`).
- ✅ Quote ingest dedupes by Gmail message id (live) / recipient (mock);
  second run ingests 0 (`test_ingest_flips_rfq_to_quoted`).
- ✅ RFQ status transitions enforced by a state machine; editing after send
  is 409 (`test_state_machine_rejects_illegal_transitions`).
- ⚠️ Award intentionally allows repeat decisions (they append to history);
  each is actor-stamped and audited.

## Background work & failure recovery
- ✅ Search/ingest progress persists in `background_jobs` (survives restarts,
  correct under multiple workers) — `test_search_job_is_persisted`,
  `test_ingest_status_survives_process_state`.
- ✅ Jobs orphaned by a crash are failed into the exception queue at boot
  (`test_orphaned_running_jobs_fail_on_boot`); documents stuck in
  'Processing' are likewise recovered (pre-existing behavior).
- ✅ Operator exception queue: `GET /api/jobs?status=error` with safe retry
  (`test_exception_queue_retry`); retry replays from recorded parameters.
- ⚠️ **Open:** jobs still execute as in-process FastAPI background tasks —
  no independent worker, no scheduled retries/backoff, no transactional
  outbox. A killed process drops in-flight work (recovered as a failed job,
  retried manually). Next step: a worker loop polling `background_jobs`.

## BOM integrity & provenance
- ✅ Approval gate: only human-confirmed documents feed package BOMs and RFQ
  generation (`test_unapproved_bom_blocks_rfq`); the model never invents
  line items (they come from structured extracted/entered data).
- ✅ Extraction provenance (source sheet, confidence, mocked flag) was
  already tracked; extraction runs in a crash-isolated subprocess.
- ⚠️ **Open:** BOM lives as JSON on the document (no per-item revision
  history); quote extraction provenance is per-quote, not per-field.

## Audit
- ✅ Append-only `audit_events` with actor id+email on every consequential
  action across the workflow (`test_audit_covers_the_whole_workflow`); the
  API exposes no mutation routes (`test_audit_is_read_only`).
- ✅ Awards create durable `purchase_decisions` records (decision maker,
  strategy, selections, totals) committed atomically with the status flips
  (`test_line_comparison_and_award_records_decision`).
- ⚠️ Append-only is enforced at the application layer, not by DB permissions.

## File storage
- ✅ Upload extension allowlist; uuid-prefixed storage names (no collisions/
  overwrites); signed short-lived preview URLs (`test_uploads.py`).
- ✅ **Object-storage abstraction** (`app/services/storage.py`): local disk
  (default) or any S3-compatible store (`PROCUREAI_STORAGE_BACKEND=s3` —
  AWS S3, Cloudflare R2, MinIO). Serving redirects to presigned URLs;
  extraction materialises a temp copy; backend is chosen per file locator so
  pre-switch local files keep working (`test_storage.py`, fake S3 client).
- ✅ SHA-256 checksum recorded on every upload (migration 0015) and stamped
  into the audit event.
- ⚠️ **Open:** no document versioning; checksum recorded but not yet used
  for duplicate detection.

## Observability
- ⚠️ **Open:** logging is ad-hoc `logging` calls; no structured logs,
  metrics, tracing, or correlation IDs. LLM/provider failures on the
  discovery path still fall back silently.

## Verification status
- Backend: 22 pytest tests green (providers force-mocked by conftest —
  tests can never send real email or call paid APIs).
- Frontend: `tsc --noEmit` + production build green; API types regenerated
  and drift-checked in CI.
- Migrations: `alembic upgrade head` from an empty database verified
  (0001 → 0014).
