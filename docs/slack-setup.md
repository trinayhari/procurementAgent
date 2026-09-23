# Slack Setup: Proq as a coworker in your channels

This guide creates the Slack app, wires it to a running Proq API, installs
it into a workspace, links channels to projects, and drives the whole path
locally without a public URL.

## How it works (read this first)

- **One Slack app, many installs.** You create the app once (below). Each
  Proq organization installs it into its own workspace from Settings; the
  bot token Slack issues is stored per organization in `slack_installations`
  and is what every outbound call uses. Nothing per-workspace goes in `.env`.
- **Channels map to projects.** A `slack_channel_links` row ties a channel to
  a project. A PM drops a plan set in `#riverside-wtp` with a sentence of
  context; the agent downloads it, runs the same intake as email, and every
  later notice for that project (BOM drafted, RFQs sent, quotes in, award
  ready, POs issued) posts back to that channel, in the thread the request
  started in.
- **What the agent listens to:** a message with files in a linked channel,
  and any `@Proq` mention (with or without files) in a channel the bot is
  in. A mention in an unlinked channel links it to whatever project the
  intake picks, so the first plan set in a fresh channel is enough.
- **Who can talk to it:** the Slack user's email (from `users.info`) must
  belong to a Proq user in the installing organization. Anyone else gets an
  ephemeral "I don't know who you are in Proq yet" and nothing happens.
- **Approve award is one click.** The award card carries an
  "Approve award" button whose value is the approval link. The click runs
  the approval server-side as the clicking user and rewrites the card into a
  confirmation with the PO numbers.
- **Every request from Slack is signed.** The API verifies
  `X-Slack-Signature` (HMAC-SHA256 over `v0:<timestamp>:<raw body>`) with
  `PROCUREAI_SLACK_SIGNING_SECRET` and rejects timestamps older than five
  minutes. With the secret empty, development accepts unsigned requests (so
  the test script works); production refuses them.

## 1. Create the Slack app

Go to <https://api.slack.com/apps>, **Create New App**, **From a manifest**,
pick the workspace you develop in, and paste this manifest. Replace
`https://api.example.com` with the public URL of the Proq API (for local
work, an ngrok or Cloudflare tunnel to `localhost:8000`).

```yaml
display_information:
  name: Proq
  description: Procurement that runs from your project channels.
  background_color: "#1f2937"
features:
  bot_user:
    display_name: Proq
    always_online: true
  slash_commands:
    - command: /proq
      url: https://api.example.com/api/webhooks/slack/commands
      description: Link this channel to a project, or check status
      usage_hint: "link <project name> | status | help"
      should_escape: false
oauth_config:
  redirect_urls:
    - https://api.example.com/api/webhooks/slack/oauth/callback
  scopes:
    bot:
      - chat:write
      - channels:history
      - groups:history
      - channels:read
      - groups:read
      - files:read
      - app_mentions:read
      - commands
      - users:read
      - users:read.email
settings:
  event_subscriptions:
    request_url: https://api.example.com/api/webhooks/slack/events
    bot_events:
      - app_mention
      - message.channels
      - message.groups
  interactivity:
    is_enabled: true
    request_url: https://api.example.com/api/webhooks/slack/interactions
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

Notes:

- Keep **exactly one** redirect URL. The API does not send `redirect_uri`
  on the authorize or exchange calls, so Slack uses the configured one; that
  way the API never has to know its own public hostname.
- `users:read` is required alongside `users:read.email` (Slack rejects the
  email scope on its own).
- Slack verifies the events URL when you save the manifest: the API must be
  running and reachable at that URL. The `url_verification` handshake is
  answered before the signature check, so it succeeds before the app exists
  and its signing secret is configured, which is the only order the setup can
  actually happen in. Every other event still requires a valid signature.

From **Basic Information**, copy the **Client ID**, **Client Secret** and
**Signing Secret**.

## 2. Environment variables

All three go in `apps/api/.env` (or the host's environment):

| Variable | What it is |
|---|---|
| `PROCUREAI_SLACK_CLIENT_ID` | Basic Information: Client ID |
| `PROCUREAI_SLACK_CLIENT_SECRET` | Basic Information: Client Secret |
| `PROCUREAI_SLACK_SIGNING_SECRET` | Basic Information: Signing Secret |
| `PROCUREAI_APP_BASE_URL` | Already used for email links; the OAuth callback redirects here (`/#/settings?slack=connected`) |

`GET /api/slack/status` reports `configured: false` and lists the missing
variables until all three are set. Restart the API after changing them.

## 3. Install into a workspace

1. Sign in to Proq, open **Settings**, click **Connect Slack** (the UI calls
   `GET /api/slack/install-url`, which returns the Slack consent URL with a
   `state` bound to your organization and user, valid for ten minutes).
2. Approve on Slack. Slack redirects to
   `/api/webhooks/slack/oauth/callback?code=...&state=...`; the API checks
   the state, exchanges the code (`oauth.v2.access`), stores the bot token,
   and sends the browser back to Settings with `?slack=connected`.
3. **Invite the bot to the channels** it should watch: `/invite @Proq` in
   each project channel. The bot only receives messages from channels it is
   a member of.

`DELETE /api/slack/installation` disconnects (revokes the token at Slack and
drops every channel link).

## 4. Link channels to projects

Any of:

- In the channel: `/proq link Riverside WTP` (fuzzy-matches the project name
  within your organization). `/proq status` shows the linked project's latest
  activity, `/proq help` the summary.
- From Settings: `PUT /api/slack/channels/{channel_id}` with
  `{"projectId": "riverside-wtp", "channelName": "riverside-wtp"}`;
  `DELETE` the same path to unlink; `GET /api/slack/channels` lists links.
- Automatically: mention `@Proq` with the first plan set in an unlinked
  channel; the channel is linked to the project intake creates or chooses.

## 5. Test locally without Slack

The public endpoints can be driven with a signed request from
`apps/api/scripts/send_test_slack_event.py`. The server still needs an
installation row for the fake team (so it has a bot token to call
`users.info` and download the file with); the easiest way is a real install
against a dev workspace through a tunnel (section 3), after which the test
script can replay events for that `team_id` without Slack in the loop.

```bash
cd apps/api
# A message with a file in a linked channel (signed with the server's secret):
.venv/bin/python scripts/send_test_slack_event.py \
  --secret "$PROCUREAI_SLACK_SIGNING_SECRET" \
  --team T0AAA --channel C0RIVER --user U0PM \
  --file-url "https://files.slack.com/files-pri/T0AAA-F1/download/c-101.pdf"

# A mention (works in an unlinked channel, auto-links it):
.venv/bin/python scripts/send_test_slack_event.py --secret ... --mention --file-url ...

# A slash command:
.venv/bin/python scripts/send_test_slack_event.py --secret ... --command "link Riverside WTP"

# An approve-award click for an approval token:
.venv/bin/python scripts/send_test_slack_event.py --secret ... --interaction --token <approval token>
```

With `PROCUREAI_SLACK_SIGNING_SECRET` empty and `PROCUREAI_ENV` not
`production`, drop `--secret`; the server skips verification.

The same signature by hand with curl:

```bash
SECRET=...; TS=$(date +%s)
BODY='{"type":"url_verification","challenge":"abc"}'
SIG="v0=$(printf 'v0:%s:%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"
curl -s -X POST http://localhost:8000/api/webhooks/slack/events \
  -H "Content-Type: application/json" \
  -H "X-Slack-Request-Timestamp: $TS" -H "X-Slack-Signature: $SIG" \
  -d "$BODY"
# prints: abc
```

## Endpoint reference

Authenticated (a signed-in member, scoped to their organization):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/slack/status` | `configured`, `installed`, team, linked channels |
| GET | `/api/slack/install-url` | The consent URL with a signed state |
| GET | `/api/slack/channels` | Linked channels with project names |
| PUT | `/api/slack/channels/{channel_id}` | Link or relink to `projectId` |
| DELETE | `/api/slack/channels/{channel_id}` | Unlink |
| DELETE | `/api/slack/installation` | Disconnect the workspace |

Public (signature-verified, or state-verified for the callback):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/webhooks/slack/oauth/callback` | End of the install flow |
| POST | `/api/webhooks/slack/events` | Events API (`url_verification`, `message`, `app_mention`) |
| POST | `/api/webhooks/slack/interactions` | Button clicks (`approve_award`) |
| POST | `/api/webhooks/slack/commands` | `/proq` |

Events are acknowledged immediately and processed in a background task;
Slack retries (`X-Slack-Retry-Num`) of an `event_id` seen in the last hour
are acknowledged and skipped (the seen set is in memory, per process).

## Troubleshooting

- **Slack shows "Your URL didn't respond"** when saving the manifest: the
  API is not reachable at the tunnel URL, or the signing secret in `.env`
  does not match the app's (every request is rejected with 401).
- **The bot never reacts to a file:** it is not a member of the channel
  (`/invite @Proq`), the channel is not linked (use `/proq link` or mention
  the bot), or the poster's Slack email is not a Proq user in the
  organization (the bot says so ephemerally).
- **Notices do not arrive in Slack:** `GET /api/slack/status` must show
  `installed: true` and the project's channel under `channels`; the bot
  must be in that channel (`not_in_channel` in the API log otherwise).
- **"invalid_code" on install:** the code was already exchanged or expired
  (codes live ten minutes); start again from Settings.
