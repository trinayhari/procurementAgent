# Email setup: agent inboxes on AgentMail

This guide takes you from zero to RFQs being emailed and supplier replies
flowing back in, including the AgentMail console steps, DNS at GoDaddy, every
`.env` variable, and how to verify it end to end without sending anything.

## How it works (read this first)

- **One agent inbox per customer organization.** The first time an
  organization sends (an RFQ, a test email, an invite) Proq creates an inbox
  for it through the AgentMail API and stores the address on the organization
  (`organizations.agentmail_inbox_id`). The username is a slug of the org name
  (`acme-construction@proq.tryproq.dev`), the display name is
  `Proq for Acme Construction`, and the org id is passed as `client_id` so a
  retried create never makes a second inbox.
- **That address is the agent's identity for the customer.** The PM emails it
  with a plan set, suppliers receive RFQs from it and reply to it, award
  notices and follow-ups go out as replies in the same threads.
- **The buyer stays visible** through the display name we record
  (`"Jane Doe: Acme Construction" <acme-construction@proq.tryproq.dev>`) and
  through Cc: each user can set a **"Copy me on emails"** address in
  **Settings**; it is added as `Cc:` on the RFQs, award notices and test
  emails they trigger. It is dropped when it would duplicate the recipient or
  the inbox. A user's own address is never the From, and there is no
  `Reply-To` pointing at the user: replies must land in the agent inbox,
  which is the only place the webhook reads.
- **Replies arrive by webhook, not polling.** One organization-level webhook
  in AgentMail posts every `message.received` event (for every inbox) to
  `POST /api/webhooks/agentmail`. The route verifies the Svix signature,
  maps the inbox to the organization, downloads attachments into document
  storage, stores the message as an `inbound_emails` row, and hands it to
  `services/inbound`. A supplier reply is attributed to its RFQ by the
  AgentMail **thread id** recorded on the recipient when the RFQ was sent
  (fallback: the `In-Reply-To` header naming a message we sent), the
  recipient gets `repliedAt`, and the reply is parsed into a quote. A later
  reply from the same supplier supersedes their earlier quote; a reply with
  no readable amount is stored as **Needs review** on the Quotes tab.
- **Not configured, then mock mode.** With `PROCUREAI_AGENTMAIL_API_KEY` empty,
  sends are logged, not delivered, and the UI says so (Settings shows
  *Not configured* and names the variable). The test suite force-blanks the
  key so tests can never send real email.
- **Configured is not the same as working.** A revoked key looks configured
  until the first real call fails. Settings shows the last AgentMail / AI
  failure, and **Check connections** (`GET /api/health/providers`) creates or
  reads the org's inbox for real so you can verify a fresh key without
  sending anything.
- **Attachment cap.** AgentMail accepts 6 MB per request with inline
  attachments (base64 inflates by about a third), so RFQs cap chosen
  documents at **4 MB** per email. Larger plan sets are better shared as a
  link; URL-backed attachments (30 MB) are the escape hatch if that ever
  changes.

---

## Step 1: API key

1. Sign in at <https://console.agentmail.to> and create an organization API
   key (**API Keys** in the sidebar). Give it the default permissions; the
   app creates inboxes, sends, replies and reads attachments.
2. Put it in `apps/api/.env` (or the service variables in production):

   ```
   PROCUREAI_AGENTMAIL_API_KEY=am_...
   ```

That alone is enough to send from AgentMail's default domain
(`<slug>@agentmail.to`), which is fine for development. Free-tier messages
carry a "Sent via AgentMail" footer; paid plans do not.

## Step 2: custom domain (`proq.tryproq.dev`)

Suppliers should see mail from your domain, not `agentmail.to`.

1. In the console go to **Domains** and add `proq.tryproq.dev` (or run
   `client.domains.create("proq.tryproq.dev")`). AgentMail returns the DNS
   records to add: an **MX** record (inbound mail), **TXT** records for SPF,
   DKIM (one or more `<selector>._domainkey` names) and DMARC (`_dmarc`).
2. Our registrar is **GoDaddy**. In the GoDaddy DNS manager for
   `tryproq.dev`, add each record under the subdomain:
   - **MX**: Name `proq`, Value the mail server AgentMail shows, Priority as
     shown (typically 10).
   - **TXT**: Name is the part before `.tryproq.dev` (`proq` for the SPF
     record, `_dmarc.proq` for DMARC, `<selector>._domainkey.proq` for DKIM);
     Value copied exactly from the console. GoDaddy accepts the long DKIM value
     as one string.
   Do not touch the apex records that serve `tryproq.dev` (marketing) or
   `app.tryproq.dev` (the web app); everything here lives under `proq.`.
3. Back in the console click **Verify**. Propagation takes minutes to a couple
   of hours; the status goes `pending` to `verifying` to `verified`. Then set:

   ```
   PROCUREAI_AGENTMAIL_DOMAIN=proq.tryproq.dev
   ```

   Inboxes created before this stay on `agentmail.to`; new organizations get
   the custom domain. To move an existing org, clear
   `organizations.agentmail_inbox_id` and the next send creates a new inbox
   (its old threads keep working: replies to them still reach the old inbox
   as long as it exists, and the webhook maps any inbox to its org).

## Step 3: inbound webhook

1. Console, **Webhooks**, **Create Webhook**:
   - URL: `https://<api host>/api/webhooks/agentmail`
     (Railway: `https://<your-app>.up.railway.app/api/webhooks/agentmail`).
   - Events: `message.received` (and `message.received.unauthenticated` if
     you want mail from senders without SPF/DKIM to be processed too; the
     route accepts both).
   - Scope: organization-level (all inboxes). Do not create one per inbox.
2. Copy the signing secret (starts with `whsec_`) and set:

   ```
   PROCUREAI_AGENTMAIL_WEBHOOK_SECRET=whsec_...
   ```

   The route verifies every delivery (`svix-id`, `svix-timestamp`,
   `svix-signature`; HMAC-SHA256 over `id.timestamp.body`, five-minute
   tolerance). With the secret empty, verification is skipped in development
   and **refused (503) in production**, so a production deploy without the
   secret drops all inbound mail loudly rather than accepting spoofed posts.
3. Optional multi-tenant isolation: create a pod in the console and set
   `PROCUREAI_AGENTMAIL_POD_ID`; inboxes are then created inside it.

## Step 4: verify

1. Restart the API and sign in.
2. **Settings** shows *Sent from* as *Not created yet* until the first send.
   Click **Check connections**: the org's inbox is created and read back, and
   the address appears.
3. Click **Send test email**: a message from the org inbox to your login
   address (Cc'd to your "Copy me" address if set). Reply to it from your mail
   client: the reply shows up under `GET /api/inbound` within seconds
   (`kind: unknown`, since a test email is not an RFQ).
4. Send a real RFQ to yourself, reply with a price, and watch the RFQ flip to
   **Quoted** with the reply in its conversation.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `PROCUREAI_AGENTMAIL_API_KEY` | Organization API key. Empty: mock sender, nothing delivered. |
| `PROCUREAI_AGENTMAIL_DOMAIN` | Verified custom domain for new inboxes. Empty: `agentmail.to`. |
| `PROCUREAI_AGENTMAIL_WEBHOOK_SECRET` | Svix signing secret of the webhook endpoint. Required in production. |
| `PROCUREAI_AGENTMAIL_POD_ID` | Optional pod to create inboxes in. |
| `PROCUREAI_AGENTMAIL_DISPLAY_NAME_PREFIX` | Inbox display name prefix, default `Proq for`. |

## Plan limits

Inboxes are the unit AgentMail meters: Free 3, Developer 10, Startup 150,
Enterprise custom (and 3k / 10k / 150k emails per month). Proq creates **one
inbox per organization**, so the plan caps the number of customer
organizations that can send. Custom domains need Developer or above. API
calls are rate limited per organization (429 with `Retry-After`); the sender
retries 429 and 5xx twice with a short pause.

## Local testing without AgentMail

The whole loop runs without an API key. Sends go through `MockSender` (logged
as `[MOCK SEND]`, nothing delivered) and the organization gets a stand-in
inbox address, `<org slug>@mock.proq.local`, the first time it sends or the
first time a delivery for that address arrives. `GET /api/auth/email-config`
reports it as `inboxAddress` (with `mocked: true`). Forge deliveries with
`scripts/send_test_inbound.py`:

```bash
cd apps/api
# A customer intake: a known user emails a plan set to the agent inbox.
.venv/bin/python scripts/send_test_inbound.py \
  --url http://localhost:8000/api/webhooks/agentmail \
  --inbox riverside-gc@mock.proq.local \
  --from "Pat Miller <pm@riverside.example>" \
  --subject "Riverside WTP site set" \
  --text "Site set attached, need it by Oct 15" \
  --attach "sample-docs/C-101 site plan.pdf"

# A supplier reply to a mock-sent RFQ, in the thread the send recorded.
.venv/bin/python scripts/send_test_inbound.py \
  --inbox riverside-gc@mock.proq.local \
  --thread <threadId from the RFQ recipient> \
  --from "Sales <sales@pipe.example>" \
  --text "Fire hydrant \$3,150 each, freight \$900, 4 weeks"
```

The script signs the payload exactly as Svix does when
`PROCUREAI_AGENTMAIL_WEBHOOK_SECRET` (or `--secret`) is set, and posts to
`http://localhost:8000/api/webhooks/agentmail` by default. `--attach` carries
the file inline (base64 `content`), which the webhook stores without an API
download. Mock sends record `mock-...` thread and message ids; while no key
is set those ids attribute a reply exactly like real ones, so `--thread` with
the recipient's `threadId` (or `--in-reply-to` with its `messageId`) lands
the reply on the RFQ, parses the quote, and runs the readiness check that
emails the award card. Once a real key is set, mock ids are ignored and the
mock inbox is replaced by a real one on first use. Production never resolves
a mock address. `tests/test_inbound_rfq_replies.py` does all of this in code.

Then **Check for replies** on the RFQ (or `POST /api/projects/{id}/quotes/ingest`)
re-runs the parse over any stored replies the webhook handler did not get
through, and `POST /api/inbound/{id}/reprocess` re-runs one row.
