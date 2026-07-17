# Email Setup — sending RFQs from your own address

This guide takes you from zero to RFQs being emailed from the address you
want, including the Google Cloud console steps, every `.env` variable, and
how to verify it end to end.

## How it works (read this first)

- The app sends all email through **one connected Gmail account**, using a
  Google OAuth *refresh token* you mint once. RFQ sends use the `gmail.send`
  scope; reading supplier quote replies uses `gmail.readonly`.
- Each user can set their own **"RFQ sender address"** in **Settings** — it
  becomes the `From:` header on RFQs they send.
- **The Gmail catch:** Gmail silently rewrites the `From:` header back to the
  connected account **unless** that address is a verified **"Send mail as"
  alias** of the connected account (Step 5). If your test email arrives
  "from" the wrong address, this is why.
- **No Gmail configured → mock mode.** Sends are logged, not delivered, and
  the UI labels them as mock. Nothing real can go out until you finish this
  guide, and the test suite force-blanks these variables so tests can never
  send real email.

---

## Step 1 — Create a Google Cloud project & enable the Gmail API

1. Go to <https://console.cloud.google.com> and sign in **as the Google
   account that will send the email** (e.g. `bids@yourcompany.com`).
2. Top bar → project picker → **New Project** → name it (e.g. `procureai-email`)
   → **Create**, then make sure it's selected.
3. **APIs & Services → Library** → search **"Gmail API"** → **Enable**.

## Step 2 — Configure the OAuth consent screen

1. **APIs & Services → OAuth consent screen** (Google may call this
   **"Google Auth Platform → Branding/Audience"** in the new console).
2. User type: **External** (unless the account is in your own Google
   Workspace org — then **Internal** is simpler and skips Step 2.5).
3. Fill the required fields (app name e.g. `ProcureAI`, support email,
   developer email). No logo/domains needed.
4. **Scopes**: you can skip adding scopes here — the token-mint script
   requests them directly. (Adding `.../auth/gmail.send` and
   `.../auth/gmail.readonly` here is fine but not required.)
5. **Test users** (External apps only): add the Gmail address from Step 1.
   Only listed test users can authorize while the app is in *Testing* status.

> ⚠️ **Token-expiry trap:** while the consent screen is in **Testing**
> status, Google expires refresh tokens after **7 days** — email will
> silently fall back to failing sends weekly. For anything beyond a quick
> trial, go to **OAuth consent screen → Publish app** ("In production").
> You do NOT need Google's verification review for your own use — ignore the
> "unverified app" warning during consent. Internal (Workspace) apps don't
> have this problem.

## Step 3 — Create the OAuth client & mint the refresh token

1. **APIs & Services → Credentials → + Create credentials →
   OAuth client ID** → Application type: **Desktop app** → **Create**.
2. **Download JSON** (a file like `client_secret_xxx.json`).
3. On your machine:

   ```bash
   cd backend
   .venv/bin/python scripts/mint_gmail_token.py path/to/client_secret_xxx.json
   ```

4. A browser opens — **sign in as the sending account**, click through the
   "Google hasn't verified this app" warning (Advanced → continue), and
   **Allow** both permissions (send + read).
5. The script prints four `PROCUREAI_GMAIL_*` lines. Keep them for Step 4.

   - "No refresh token returned"? Revoke the app's prior access at
     <https://myaccount.google.com/permissions> and re-run.

## Step 4 — Configure the backend `.env`

Edit `backend/.env` (create it from `backend/.env.example` if needed):

```bash
PROCUREAI_GMAIL_CLIENT_ID=<from the script output>
PROCUREAI_GMAIL_CLIENT_SECRET=<from the script output>
PROCUREAI_GMAIL_REFRESH_TOKEN=<from the script output>
# Workspace default From address — used when a user hasn't set their own.
# Must be the connected account itself or one of its verified aliases (Step 5).
PROCUREAI_GMAIL_SENDER_ADDRESS=bids@yourcompany.com

# Optional: how far back quote ingest scans for supplier replies (days).
PROCUREAI_QUOTE_INGEST_LOOKBACK_DAYS=30
```

Restart the backend. `.env` is git-ignored — **never commit it**, and rotate
any credential that leaks.

## Step 5 — Send from a different address (the "Send mail as" alias)

Skip this if everyone should send from the connected account's own address.

To send from any OTHER address (your personal work email, a shared
`procurement@` box, etc.), that address must be a **verified alias of the
connected Gmail account**:

1. Open **Gmail** (the connected account) → ⚙️ **See all settings** →
   **Accounts and Import** → **"Send mail as"** → **Add another email address**.
2. Enter the name + address you want to send as. Leave "Treat as an alias"
   checked. For a non-Gmail address Google asks for your mail server's SMTP
   details, or (Workspace, same domain) verifies directly.
3. Google emails a **verification code** to that address — enter it.
4. Done. The Gmail API will now honor that address in the `From:` header.

Without this step, Gmail **silently replaces** your chosen From with the
connected account's address — the send succeeds, but suppliers see the wrong
sender.

> Google Workspace tip: an admin can pre-approve domain aliases under
> Admin console → Apps → Google Workspace → Gmail → End User Access.

## Step 6 — Set your per-user sender in the app

1. Log in → **Settings** → **"RFQ sender address"** → enter the address from
   Step 5 → **Save**. (Clearing it falls back to
   `PROCUREAI_GMAIL_SENDER_ADDRESS`.)
2. Each user has their own — RFQs they send use their address.

## Step 7 — Verify

In the app: **Settings → Email delivery → "Send test email"**. It sends a
message **to your own login email** through exactly the RFQ path and tells
you the From address used.

- ✅ Arrived, From is correct → you're done.
- ✅ Arrived, but From shows the connected account → Step 5 (alias) is
  missing or unverified for your address.
- "Mock mode — no Gmail connected" → the three `PROCUREAI_GMAIL_*` creds
  aren't all set where the backend runs (check Step 4 / Step 8).
- Error mentioning `invalid_grant` → the refresh token was revoked or
  expired (Testing-status 7-day trap — see Step 2). Re-run Step 3.

Or from a terminal:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"..."}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["accessToken"])')
curl -s -X POST http://localhost:8000/api/auth/test-email -H "Authorization: Bearer $TOKEN"
```

Every test send is recorded in the audit log (`GET /api/audit?action=email.test_sent`).

## Step 8 — Production (Railway / Render)

Set the same four variables in the host's service environment — **not** in a
committed file:

- Railway: service → **Variables** tab.
- Render: service → **Environment** tab (they're already declared as blank
  secrets in `render.yaml`).

```
PROCUREAI_GMAIL_CLIENT_ID
PROCUREAI_GMAIL_CLIENT_SECRET
PROCUREAI_GMAIL_REFRESH_TOKEN
PROCUREAI_GMAIL_SENDER_ADDRESS
```

Redeploy, then repeat Step 7 against the production URL.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Test email says **mock mode** | One of client id / secret / refresh token is empty in the environment the backend actually runs in. Env vars override `.env`. |
| From address rewritten to the connected account | The address isn't a verified **Send mail as** alias (Step 5). |
| `invalid_grant` on send | Refresh token revoked, or consent screen still in **Testing** (7-day expiry) — publish the app and re-mint (Step 2/3). |
| Works for a week, then stops | Same 7-day Testing expiry. Publish the app. |
| Quote ingest finds nothing | The token was minted send-only. Re-run Step 3 — the script requests `gmail.send` **and** `gmail.readonly`. Also check `PROCUREAI_QUOTE_INGEST_LOOKBACK_DAYS`. |
| `429 Too many attempts` on the test button | Rate-limited to 3 test sends/minute. |
| Gmail daily sending limits | Consumer Gmail ≈ 500 recipients/day, Workspace ≈ 2 000/day. RFQ sends cap at 10 recipients each. |

## Security notes

- The refresh token grants **send + read** on the connected mailbox — treat
  it like a password. Rotate it (revoke at
  <https://myaccount.google.com/permissions>, re-mint) if it ever leaks.
- Duplicate-send protection, per-recipient failure tracking, and audit
  logging apply to all sends — see [reliability-review.md](reliability-review.md).
