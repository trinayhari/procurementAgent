# Production Checklist — from merge to live

The app runs with **zero API keys** (every provider falls back to a
clearly-flagged mock), so bring it up in stages: required config first,
then each provider as you obtain its key. Companion guides:
[DEPLOYMENT.md](../DEPLOYMENT.md) (hosting) and
[email-setup.md](email-setup.md) (Gmail, step by step).

## 0. One-time cleanup
- [ ] Merge the production-hardening PR.
- [ ] **Rotate any previously exposed credentials**: revoke the old Gmail
      token at <https://myaccount.google.com/permissions>; delete the old
      OpenRouter and Google Maps keys in their consoles. Mint fresh ones
      below — never reuse leaked values.

## 1. Required backend variables (Railway service → Variables)
| Variable | Value / source |
| --- | --- |
| `PROCUREAI_ENV` | `production` — enables the JWT-secret boot guard |
| `PROCUREAI_JWT_SECRET` | `openssl rand -hex 32` |
| `PROCUREAI_DATABASE_URL` | add a Railway **Postgres** service, reference `${{Postgres.DATABASE_URL}}` |
| `PROCUREAI_CORS_ORIGINS` | `["https://<your-app>.vercel.app"]` — JSON array, exact origin |

Leave `PROCUREAI_SEED_DEMO_DATA` unset — production gets no demo account;
register the first user through the UI. Migrations run automatically at
deploy (`alembic upgrade head` in the start command).

(Render instead of Railway? `render.yaml` provisions Postgres, the JWT
secret, and `PROCUREAI_ENV` automatically — you only fill the blanks.)

## 2. Frontend (Vercel → Settings → Environment Variables)
- [ ] `VITE_API_URL` = the backend URL. Build-time variable — **redeploy the
      frontend after changing it**.

## 3. Provider keys (each optional; empty ⇒ flagged mock)

### a. OpenAI / OpenRouter — live BOM & quote extraction
- Key from <https://platform.openai.com> (or <https://openrouter.ai>).
- [ ] `PROCUREAI_OPENAI_API_KEY`
- [ ] OpenRouter only: `PROCUREAI_OPENAI_BASE_URL=https://openrouter.ai/api/v1`
      and `PROCUREAI_OPENAI_VISION_MODEL=openai/gpt-4.1`

### b. Google Maps — live supplier discovery
- Google Cloud console → enable **Geocoding API** + **Places API** (billing
  on) → Credentials → API key, restricted to those two APIs.
- [ ] `PROCUREAI_GOOGLE_MAPS_API_KEY`

### c. Gmail — live RFQ send + quote-reply ingest
- Follow [email-setup.md](email-setup.md) (OAuth client → mint refresh token
  → **publish the consent screen**, or the token expires every 7 days →
  "Send mail as" alias for custom From addresses).
- [ ] `PROCUREAI_GMAIL_CLIENT_ID`
- [ ] `PROCUREAI_GMAIL_CLIENT_SECRET`
- [ ] `PROCUREAI_GMAIL_REFRESH_TOKEN`
- [ ] `PROCUREAI_GMAIL_SENDER_ADDRESS`

### d. S3-compatible storage — uploads that survive redeploys (recommended)
Cloudflare R2 (free tier) or AWS S3: create a bucket + access key scoped to it.
- [ ] `PROCUREAI_STORAGE_BACKEND=s3`
- [ ] `PROCUREAI_S3_BUCKET`
- [ ] `PROCUREAI_S3_ACCESS_KEY_ID` / `PROCUREAI_S3_SECRET_ACCESS_KEY`
- [ ] R2/MinIO: `PROCUREAI_S3_ENDPOINT_URL` · AWS: `PROCUREAI_S3_REGION`

Without this, raw uploaded PDFs are lost on each redeploy (extracted BOM
data still persists in Postgres). Files stored locally before the switch
keep working.

## 4. Verify
1. `GET https://<backend>/health` → `{"status":"ok"}`. A refusal to boot
   means the JWT-secret guard fired — check §1.
2. Open the app → **register** the first account.
3. Settings → set your RFQ sender address → **Send test email** — confirms
   the Gmail path and shows the effective From address.
4. Upload a plan PDF → extraction should run without a "mock" badge; after
   the next redeploy the file should still preview (S3 working).
5. Run a supplier search → results should not say "mock results".
6. Send an RFQ to yourself (add yourself as a manual supplier) end to end.
7. Spot-check `GET /api/audit` — every step above should be recorded.

## Ongoing
- Secrets live only in host env vars — never in committed files.
- Watch `GET /api/jobs?status=error` (exception queue) for failed
  background work; failed jobs are retryable from there.
- Gmail sending limits: consumer ≈500 recipients/day, Workspace ≈2 000/day.
