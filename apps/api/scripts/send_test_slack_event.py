"""Post a signed, fake Slack request to a local Proq server.

Stands in for Slack while developing without a public URL: it signs the body
exactly like Slack does (v0:<timestamp>:<body>, HMAC-SHA256 with the signing
secret) and posts it to the events, interactions or commands endpoint.

    python scripts/send_test_slack_event.py --team T0AAA --channel C0RIVER --user U0PM
    python scripts/send_test_slack_event.py --interaction --token <approval token>
    python scripts/send_test_slack_event.py --command "link Riverside WTP"

The server resolves the Slack user through users.info and downloads the file
with the bot token, so a real installation row (team_id + bot token) must
exist for --team; see docs/slack-setup.md. With an empty
PROCUREAI_SLACK_SIGNING_SECRET the server skips verification in development,
so --secret may be omitted then.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def post(url: str, body: bytes, content_type: str, secret: str) -> None:
    ts = str(int(time.time()))
    headers = {"Content-Type": content_type, "X-Slack-Request-Timestamp": ts}
    if secret:
        headers["X-Slack-Signature"] = sign(secret, ts, body)
    req = Request(url, data=body, headers=headers, method="POST")
    with urlopen(req) as resp:
        print(resp.status, resp.read().decode() or "(empty body)")


def message_event(args) -> dict:
    files = []
    if args.file_url:
        files.append(
            {
                "id": "F0TEST",
                "name": args.file_name,
                "mimetype": "application/pdf",
                "size": 0,
                "url_private_download": args.file_url,
            }
        )
    event = {
        "type": "app_mention" if args.mention else "message",
        "channel": args.channel,
        "user": args.user,
        "text": args.text,
        "ts": f"{time.time():.6f}",
        "files": files,
    }
    if files and not args.mention:
        event["subtype"] = "file_share"
    return {
        "type": "event_callback",
        "team_id": args.team,
        "api_app_id": "A0TEST",
        "event_id": f"Ev{int(time.time() * 1000)}",
        "event_time": int(time.time()),
        "event": event,
    }


def approve_payload(args) -> dict:
    return {
        "type": "block_actions",
        "team": {"id": args.team},
        "user": {"id": args.user, "team_id": args.team},
        "channel": {"id": args.channel},
        "message": {"ts": args.message_ts},
        "container": {"type": "message", "message_ts": args.message_ts, "channel_id": args.channel},
        "response_url": "https://hooks.slack.com/actions/test",
        "actions": [
            {
                "type": "button",
                "action_id": "approve_award",
                "block_id": "b1",
                "value": f"{args.app_base}/#/approve/{args.token}",
            }
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://localhost:8000", help="API base URL")
    p.add_argument("--secret", default="", help="PROCUREAI_SLACK_SIGNING_SECRET of the server")
    p.add_argument("--team", default="T0AAA")
    p.add_argument("--channel", default="C0RIVER")
    p.add_argument("--user", default="U0PM")
    p.add_argument("--text", default="Riverside WTP site set, need it by Oct 15")
    p.add_argument("--file-url", default="", help="url_private_download to attach (a message with no file in an unlinked channel is ignored)")
    p.add_argument("--file-name", default="C-101 site plan.pdf")
    p.add_argument("--mention", action="store_true", help="send an app_mention instead of a message")
    p.add_argument("--interaction", action="store_true", help="post an approve_award button click")
    p.add_argument("--token", default="tok_test", help="approval token for --interaction")
    p.add_argument("--message-ts", default="1700000000.000300")
    p.add_argument("--app-base", default="http://localhost:5173")
    p.add_argument("--command", default="", help='slash command text, e.g. "link Riverside WTP" or "status"')
    args = p.parse_args()

    if args.interaction:
        body = urlencode({"payload": json.dumps(approve_payload(args))}).encode()
        post(f"{args.base}/api/webhooks/slack/interactions", body, "application/x-www-form-urlencoded", args.secret)
    elif args.command:
        form = {
            "command": "/proq", "text": args.command, "team_id": args.team, "channel_id": args.channel,
            "channel_name": "riverside-wtp", "user_id": args.user, "response_url": "https://hooks.slack.com/commands/test",
        }
        post(f"{args.base}/api/webhooks/slack/commands", urlencode(form).encode(), "application/x-www-form-urlencoded", args.secret)
    else:
        body = json.dumps(message_event(args)).encode()
        post(f"{args.base}/api/webhooks/slack/events", body, "application/json", args.secret)


if __name__ == "__main__":
    main()
