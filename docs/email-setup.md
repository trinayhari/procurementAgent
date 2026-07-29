# Email Setup — connecting the workspace mailbox

This guide takes you from zero to RFQs being emailed, including the Google
Cloud console steps, every `.env` variable, and how to verify it end to end.

> **No "Send mail as" alias needed any more.** Outbound mail now always comes
> from the one connected Gmail account, so the fiddly per-user alias
> verification this guide used to require is gone. If you set aliases up for
> Proq previously, you can remove them (see
> [Undoing the old alias setup](#undoing-the-old-alias-setup)).

## How it works (read this first)

- The app sends all email through **one connected Gmail account**, using a
  Google OAuth *refresh token* you mint once. RFQ sends use the `gmail.send`
  scope; reading supplier quote replies uses `gmail.readonly`.
- **Every message is `From:` that account** — the address in
  `PROCUREAI_GMAIL_SENDER_ADDRESS`. There is no per-user From address.
- **The buyer stays visible** through the display name. A send by Jane Doe of
  Acme Construction goes out as
  `"Jane Doe — Acme Construction" <bids@yourcompany.com>`. Missing name or
  company just shortens the label.
- **Users are copied, not impersonated.** Each user can set a **"Copy me on
  emails"** address in **Settings**; it is added as `Cc:` on the RFQs, award
  notices and test emails they trigger, so they keep a record. It is dropped
  when it would duplicate the recipient or the sending mailbox.
- **Replies deliberately go to the connected mailbox** — there is no
  `Reply-To:` pointing at the user. That inbox is what quote ingest reads and
  what rebuilds each RFQ conversation, so redirecting replies would silently
  break both.
- **Why one mailbox:** Gmail rewrites the `From:` header back to the connected
  account unless the address is a verified alias, which used to make sends
  arrive from the "wrong" sender. Sending from the account itself removes that
  failure mode entirely.
- **No Gmail configured → mock mode.** Sends are logged, not delivered, and
  the UI says so explicitly (Settings → **Sent from** shows *Not configured*).
  Nothing real can go out until you finish this guide, and the test suite
  force-blanks these variables so tests can never send real email.

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
3. Fill the required fields (app name e.g. `Proq`, support email,
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
   cd apps/api
   .venv/bin/python scripts/mint_gmail_token.py path/to/client_secret_xxx.json
   ```

4. A browser opens — **sign in as the sending account**, click through the
   "Google hasn't verified this app" warning (Advanced → continue), and
   **Allow** both permissions (send + read).
5. The script prints four `PROCUREAI_GMAIL_*` lines. Keep them for Step 4.

   - "No refresh token returned"? Revoke the app's prior access at
     <https://myaccount.google.com/permissions> and re-run.

## Step 4 — Configure the backend `.env`

Edit `apps/api/.env` (create it from `apps/api/.env.example` if needed):

```bash
PROCUREAI_GMAIL_CLIENT_ID=<from the script output>
PROCUREAI_GMAIL_CLIENT_SECRET=<from the script output>
PROCUREAI_GMAIL_REFRESH_TOKEN=<from the script output>
# The one From address for ALL outbound mail. Set it to the address of the
# account you authorized in Step 3 — anything else gets rewritten by Gmail.
PROCUREAI_GMAIL_SENDER_ADDRESS=bids@yourcompany.com

# Optional: how far back quote ingest scans for supplier replies (days).
PROCUREAI_QUOTE_INGEST_LOOKBACK_DAYS=30
```

Restart the backend. `.env` is git-ignored — **never commit it**, and rotate
any credential that leaks.

The three OAuth vars decide *whether* mail is delivered; the sender address
decides *what it says*. Settings → **Sent from** reports both, and
`GET /api/auth/email-config` returns them as
`{configured, mocked, senderAddressSet, fromAddress, fromHeader, ccEmail}`.

## Step 5 — Get yourself copied (per user, optional)

1. Log in → **Settings** → **"Copy me on emails"** → enter your own address →
   **Save**. Clearing it stops the copies.
2. That address is `Cc:`'d on the RFQs and award notices **you** send, so the
   thread is in your mailbox too. It never changes who the email is from, and
   it is skipped when it would just duplicate the recipient.
3. Nothing to configure in Gmail — no alias, no verification.

> Replying from your own mailbox is fine for one-off notes, but keep the
> conversation on the workspace mailbox where you can: quote ingest only reads
> that inbox.

## Step 6 — Verify

In the app: **Settings → Email delivery → "Send test email"**. It sends a
message **to your own login email** through exactly the RFQ path and reports
the From address and Cc it used.

- ✅ Arrived from `Your Name — Your Company <PROCUREAI_GMAIL_SENDER_ADDRESS>`
  → you're done. That is the expected sender for every user.
- ✅ Arrived, but from the connected account with **no** display name → the
  account has no name/company set (Settings shows what's on file).
- Settings → **Sent from** shows *Not configured*, or the test says "Mock
  mode" → the three `PROCUREAI_GMAIL_*` creds aren't all set where the backend
  runs (check Step 4 / Step 7).
- Sent from `rfq@procureai.local` → that is the placeholder used when
  `PROCUREAI_GMAIL_SENDER_ADDRESS` is empty; it is not a real mailbox. Set the
  variable.
- Error mentioning `invalid_grant` → the refresh token was revoked or
  expired (Testing-status 7-day trap — see Step 2). Re-run Step 3.

Or from a terminal:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"..."}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["accessToken"])')
curl -s -X GET  http://localhost:8000/api/auth/email-config -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://localhost:8000/api/auth/test-email  -H "Authorization: Bearer $TOKEN"
```

`email-config` answers "is this wired up?" without sending anything; the test
send goes out for real when Gmail is configured. Every test send is recorded in
the audit log (`GET /api/audit?action=email.test_sent`).

## Step 7 — Production (Railway / Render)

Set the same four variables in the host's service environment — **not** in a
committed file:

- Railway: service → **Variables** tab → **New Variable** for each (or
  **Raw Editor** to paste all four at once). Railway restarts the service on
  save.
- Render: service → **Environment** tab (they're already declared as blank
  secrets in `render.yaml`).

```
PROCUREAI_GMAIL_CLIENT_ID
PROCUREAI_GMAIL_CLIENT_SECRET
PROCUREAI_GMAIL_REFRESH_TOKEN
PROCUREAI_GMAIL_SENDER_ADDRESS
```

Environment variables override anything in `.env`, and the backend reads them
at startup — so a value changed in the dashboard needs a redeploy/restart to
take effect. Then repeat Step 6 against the production URL.

## Undoing the old alias setup

Earlier versions used each user's own address as the `From:` header, which
required verifying it as a **"Send mail as"** alias on the connected Gmail
account. Nothing reads those aliases now. To clean up:

1. Gmail (the connected account) → ⚙️ **See all settings** → **Accounts and
   Import** → **"Send mail as"** → **delete** the addresses you added for Proq.
2. Leave the account's own address in place — that's the one Proq sends from.

Addresses users had entered as their sender were carried over automatically as
their **"Copy me on emails"** address by migration `0016_user_cc_email`; no one
needs to re-enter anything.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Test email says **mock mode** | One of client id / secret / refresh token is empty in the environment the backend actually runs in. Env vars override `.env`. |
| Mail arrives from `rfq@procureai.local` | `PROCUREAI_GMAIL_SENDER_ADDRESS` is empty — that string is the "unconfigured" placeholder, not a mailbox. Set it (Step 4/7) and restart. |
| Suppliers see the connected account, not the user | Expected — that's the design. The user's name and company appear as the display name, and they're Cc'd (Step 5). |
| Gmail rewrote my From address | Only happens if you point `PROCUREAI_GMAIL_SENDER_ADDRESS` at an address the token doesn't own. Use the account you authorized in Step 3. |
| No Cc on outgoing mail | The user hasn't set **"Copy me on emails"**, or their Cc equals the recipient (a duplicate copy is dropped on purpose). |
| Supplier replies never show up | Replies land in the connected mailbox by design (there is no `Reply-To`). If they're missing, check the token has `gmail.readonly` — see the row below. |
| `invalid_grant` on send | Refresh token revoked, or consent screen still in **Testing** (7-day expiry) — publish the app and re-mint (Step 2/3). |
| Works for a week, then stops | Same 7-day Testing expiry. Publish the app. |
| Quote ingest finds nothing | The token was minted send-only. Re-run Step 3 — the script requests `gmail.send` **and** `gmail.readonly`. Also check `PROCUREAI_QUOTE_INGEST_LOOKBACK_DAYS`. |
| `429 Too many attempts` on the test button | Rate-limited to 3 test sends/minute. |
| Gmail daily sending limits | Consumer Gmail ≈ 500 recipients/day, Workspace ≈ 2 000/day. RFQ sends cap at 10 recipients each; a Cc counts toward the recipient total. |

## Security notes

- The refresh token grants **send + read** on the connected mailbox — treat
  it like a password. Rotate it (revoke at
  <https://myaccount.google.com/permissions>, re-mint) if it ever leaks.
- Duplicate-send protection, per-recipient failure tracking, and audit
  logging apply to all sends — see [reliability-review.md](reliability-review.md).
