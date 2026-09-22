# Proq as a coworker: architecture contract

Proq is an agent the customer talks to by email and Slack. Nobody has to learn
a dashboard to start a buy: a PM forwards the plan set (or posts it in the
project channel) with a sentence of context, and the agent picks it up, builds
the BOM, cuts packages, sources and levels quotes, chases suppliers, and posts
an award card back where the conversation started. One click or one reply
issues the POs. The dashboard is the agent's notebook: comparison, audit
trail, overrides.

This document is the contract the workstreams build against. It lives on the
`feat/agent-core` branch with the scaffold modules it describes.

## The loop

```
customer email / Slack ──▶ inbound ──▶ intake ──▶ project + document + extraction
   (to the org's agent inbox: acme@proq.tryproq.dev)
                                                  │
                             notify ◀── domain events (bom.drafted, rfq.sent,
                               │        quotes.received, award.ready, po.issued)
      email / Slack ◀──────────┘  status lines + Action buttons (approval links)
                                                  │
supplier reply ──▶ inbound ──▶ rfq_replies ──▶ quote parse ──▶ comparison
                                                  ▲
                        scheduler ──▶ followups (chase non-responders)
```

## Shared modules (already on the branch)

| Module | Role | Owner stream |
|---|---|---|
| `app/config.py` | All new settings are already declared (AgentMail, Slack, follow-ups, approvals). Do not add more without need; if you must, append in your own section. | shared |
| `app/services/notify/__init__.py` | `Notice`, `Action`, `ThreadRef`, `Notifier` protocol, `register()`, `emit()`. Every channel plugs in here. | C defines events, E adds Slack |
| `app/models/inbound_email.py` | `inbound_emails` table: every email an agent inbox receives, stored before processing (with AgentMail `inbox_id` / `thread_id`). Already registered in `models/__init__` and `db.SCOPED_TABLES`. | A |
| `app/models/organization.py` | `agentmail_inbox_id`: the org's agent inbox, created lazily. | A |
| `app/services/inbound/__init__.py` | `handle(db, msg)` dispatcher: attributes a row (`rfq_reply` / `intake` / `unknown`) then routes it. | shared (do not edit) |
| `app/services/inbound/rfq_replies.py` | `attribute()` + `handle()` stubs for supplier replies. | A |
| `app/services/inbound/intake.py` | `attribute()` + `handle()` stubs for customer requests. | B |
| `app/services/scheduler.py` | `register(name, interval_s, fn)`, `start()`, `run_once()`. Started from `main.py`. | D registers jobs |
| `app/api/routes/webhooks_agentmail.py` | Empty public router at `/api/webhooks/agentmail`. | A |
| `app/api/routes/webhooks_slack.py` | Empty public router at `/api/webhooks/slack`. | E |
| `app/api/routes/approvals.py` | Empty public router at `/api/approvals`. | C |
| `tests/conftest.py` | Blanks AgentMail/Slack creds and disables follow-ups for tests. | shared |

## Workstreams

### A. Email transport on AgentMail (replaces Gmail entirely)

The agent has its own inbox per customer organization, created through the
AgentMail API (`client.inboxes.create(username=<org slug>, domain=
settings.agentmail_domain, display_name="Proq for <Org>")`) the first time the
org needs to send or receive mail, and stored on `Organization.agentmail_inbox_id`.
That address is the agent's identity for that customer: the PM emails it,
suppliers receive RFQs from it and reply to it. Users are still Cc'd on RFQs
so they keep a copy; they are never the From address.

Outbound: an `AgentMailSender` implementing the existing `EmailSender`
protocol in `services/rfq/sender.py`, using `client.inboxes.messages.send`
for a new conversation and `client.inboxes.messages.reply` when replying
in-thread (so AgentMail sets In-Reply-To/References). The sender needs the
org's inbox, so `get_sender(db, org_id)` resolves (or creates) the inbox;
`SentMessage.message_id` and `thread_id` are AgentMail's ids. Record the
`thread_id` on every RFQ recipient dict: it is the attribution key for
replies. Use the official `agentmail` Python SDK.

Inbound: one org-level AgentMail webhook (`message.received`) posts to
`POST /api/webhooks/agentmail`. The route verifies the Svix signature
(`settings.agentmail_webhook_secret`; skip only when empty AND
`settings.env != "production"`), maps `inbox_id` to the organization,
downloads attachments through the API into `services/storage.py`, inserts an
`InboundEmail` row (idempotent on `provider_message_id`, with `inbox_id`,
`thread_id`, and `text` = `extracted_text` when present), and calls
`services.inbound.handle`.

Attribution in `services/inbound/rfq_replies.py`: `thread_id` matches a
recipient's recorded `threadId` → `rfq_reply` (fallback: In-Reply-To matches
a recorded `messageId`). Consumers to move off Gmail: `services/quotes/ingest.py`
(reads unprocessed `inbound_emails` rows), `services/rfq/conversation.py`
(thread = `client.threads.get(thread_id)` rendered for display, with the
stored rows as an offline fallback), `services/rfq/award_notify.py` (reply in
the winner's thread). Delete `services/quotes/gmail_reader.py`,
`scripts/mint_gmail_token.py`, the Gmail settings and deps, and rewrite
`docs/email-setup.md` for AgentMail (custom domain DNS, webhook, env vars).
`GET /api/auth/email-config` reports the org's inbox address and AgentMail
status instead.

### B. Conversational intake by email

`services/inbound/intake.py`. `attribute()`: the row's `organization_id` is
already set from the inbox; the sender email matches a `User` in that org →
return True. `handle()`:

1. Resolve the project. Use the subject/body and existing project names for the
   org (LLM call through the existing OpenAI client, with a deterministic
   fallback: exact/fuzzy name match, else create a project named from the
   subject). Persist the choice on `msg.project_id`.
2. Store each PDF/image attachment as a document on that project, reusing the
   upload path in `api/routes/documents.py` (factor the post-validation part of
   `upload_document` into a service function both can call; do not duplicate).
   Plan type: infer from filename/body (site, building, electrical, other) with
   the registry in `services/extraction/registry.py`.
3. Kick off extraction exactly as an upload does.
4. Emit `notify.Notice(kind="intake.received", thread=ThreadRef(channel="email", ...))`
   acknowledging what was understood (project, files, plan types, any need-by
   date parsed from the text) so the customer sees a reply in their thread.
5. When extraction finishes, emit `bom.drafted` on the same thread (hook the
   end of `documents._run_pipeline`; stream C owns the event names, use them).

Also handle a message with no attachment (a question or an addendum note):
reply that it was logged on the project as a note (store as a ProjectEvent).

### C. Domain events, approval links, PO numbers

1. Define the notice kinds and emit them from the existing flows:
   `bom.drafted` (end of extraction pipeline), `rfq.sent` (after a send),
   `quotes.received` (end of ingest job), `award.ready` (when every recipient
   has replied or the first follow-up window has lapsed and at least one quote
   exists: compute in a small `services/rfq/readiness.py`), `award.approved`,
   `po.issued`.
2. `EmailNotifier` in `services/notify/email.py`: renders a notice as a plain
   email (title, lines, action links) and sends via `get_sender()`, replying
   in-thread when `ThreadRef.channel == "email"`, otherwise to the project's
   requesting user (the last intake sender, else the org's first user). Register
   it at import from `main.py`.
3. `ActivityNotifier`: writes the notice to `repositories/events.log` so the
   dashboard activity feed shows the same stream.
4. Approval tokens: `models/approval_token.py` (id, org, project, package,
   payload JSON = the `AwardRequest` the recommendation would submit, token,
   expires_at, used_at, decided_by_email). `award.ready` notices carry an
   `Action("Approve award", url=<app_base_url>/#/approve/<token>)`.
   `GET /api/approvals/{token}` returns a preview (package, suppliers, totals);
   `POST /api/approvals/{token}` executes the same code path as
   `POST .../packages/{pkg}/award` (factor `_award_locked` so both call it),
   marks the token used, emits `award.approved` + `po.issued`.
5. PO numbers: add `po_numbers` JSON to `purchase_decisions` (one per winning
   supplier, format `PO-<org seq>-<n>` from an org-level counter) and put them
   in the award email body and the `po.issued` notice.
6. Web: a public `#/approve/<token>` page in `apps/web` modelled on
   `AcceptInvite.tsx`: shows the preview, one Approve button, done state.

### D. Follow-up engine

`services/rfq/followups.py`, registered with `scheduler` at import from
`main.py` (respect `settings.followup_enabled`). Policy from `design.md`
section 11 and the `followup_*` settings: for every sent RFQ recipient with
no quote yet (a `Quote` row with that `rfq_id` + supplier email), send the
first nudge after `followup_first_delay_hours`, the second after
`followup_second_delay_hours`, never more than `followup_max`, only inside
allowed hours/weekdays. Persist per-recipient state on `Rfq.recipients` JSON
(`followups: [{sentAt, messageId}]`, `repliedAt`) so restarts are safe; take
the `locks.exclusive` lock per RFQ while sending. Draft text with the existing
RFQ generator's LLM path when configured, template otherwise. Send through
`get_sender()` in the original thread. Emit `followup.sent`. Expose
`GET /api/projects/{id}/rfqs/{rfq_id}/followups` for the dashboard and delete
the demo stub in `api/routes/rfqs.py`.

### E. Slack

1. `models/slack_installation.py` (org, team_id, bot_token encrypted-at-rest is
   fine to skip for now, installed_by, created_at) and
   `models/slack_channel_link.py` (org, project_id, channel_id, channel_name).
2. OAuth install: `GET /api/slack/install` (redirect) + `GET /api/slack/oauth/callback`
   (authed by state token bound to the org). Settings UI can wait; expose the
   install URL through `GET /api/auth/email-config`-style status endpoint
   `GET /api/slack/status`.
3. `SlackNotifier` in `services/notify/slack.py`: posts a Block Kit message to
   the project's linked channel (or replies in `ThreadRef.slack_thread_ts`);
   `Action` with `style="primary"` renders as a button whose `value` is the
   action url. Register at import from `main.py`.
4. `POST /api/webhooks/slack/events` (url_verification + `message` events with
   files, in linked channels: download the file with the bot token, then run the
   same intake service as email with `ThreadRef(channel="slack")`; and
   `app_mention` for questions) and `POST /api/webhooks/slack/interactions`
   (button click → `POST /api/approvals/{token}` internally, then update the
   message). Verify Slack signatures with `settings.slack_signing_secret`.
5. Channel linking: `/proq link <project>` slash command, or auto-link when the
   intake creates the project from a channel.

Stream E may stub the call into intake (`services.inbound.intake.handle_slack`)
if stream B has not merged; define the function signature in your PR
description so the merge is mechanical.

## Ground rules for every stream

- Branch from `feat/agent-core`. Keep changes inside your files above plus the
  minimum edits to existing flows you were told to hook. Do not edit
  `services/inbound/__init__.py`, `services/notify/__init__.py`,
  `services/scheduler.py`, or `config.py` unless the contract is wrong; if it
  is, say so in your report instead of silently changing it.
- Models: add the ORM model and register it in `models/__init__.py` and
  `db.SCOPED_TABLES` when it has `organization_id`. Do NOT write an Alembic
  migration; one migration is generated after the merge.
- Tests: pytest under `apps/api` with the venv at `apps/api/.venv/bin/python`.
  Provider creds are blanked by `conftest.py`; never send real email. Add
  tests for every new endpoint and service (the suite is 480 tests; keep it
  green).
- Mock transports when creds are empty, exactly as `MockSender` does today.
- Sending needs an org: `get_sender(db, org_id)`. Streams that only have the
  protocol today should call it that way; stream A owns the signature.
- Copy: no em dashes anywhere (code comments, emails, UI). Use colons, commas,
  periods.
- Python 3.11 compatible (prod), no new heavy dependencies without a reason;
  `httpx` is already available for HTTP APIs (use it for Slack rather than
  adding an SDK); the official `agentmail` Python SDK is the one new dependency.
