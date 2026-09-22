"""Forge an AgentMail `message.received` delivery against a local server.

Runs the whole inbound path (store, attribute, quote parse, conversation)
without an AgentMail account: the payload is signed the way Svix signs real
deliveries when a webhook secret is known, and posted to the local API.

    .venv/bin/python scripts/send_test_inbound.py \\
        --inbox acme@proq.tryproq.dev \\
        --thread thr_abc123 \\
        --from "Sales <sales@pipe.example>" \\
        --text "Fire hydrant $3,150 each, freight $900, 4 weeks"

The organization must own `--inbox` (organizations.agentmail_inbox_id) or the
server drops the message. `--thread` should be the `threadId` recorded on the
RFQ recipient; `--in-reply-to` (the recipient's `messageId`) is the fallback
attribution. See docs/email-setup.md, "Local testing without AgentMail".
"""
import argparse
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.email.agentmail_client import sign_payload  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8000/api/webhooks/agentmail")
    ap.add_argument("--inbox", required=True, help="the org's agent inbox address")
    ap.add_argument("--from", dest="sender", default="Sales <sales@pipe.example>")
    ap.add_argument("--subject", default="Re: RFQ")
    ap.add_argument("--text", default="Grand total $12,345.00 delivered, 3 weeks")
    ap.add_argument("--thread", default="", help="AgentMail thread id (recipient threadId)")
    ap.add_argument("--in-reply-to", default="", help="message id we sent (recipient messageId)")
    ap.add_argument("--message-id", default=None, help="provider message id (random when omitted)")
    ap.add_argument("--secret", default=os.environ.get("PROCUREAI_AGENTMAIL_WEBHOOK_SECRET", ""),
                    help="whsec_... to sign with (empty: unsigned, dev servers accept that)")
    args = ap.parse_args()

    mid = args.message_id or f"<{uuid.uuid4().hex}@supplier.example>"
    payload = {
        "type": "event",
        "event_type": "message.received",
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "message": {
            "inbox_id": args.inbox,
            "thread_id": args.thread or f"thr_{uuid.uuid4().hex[:8]}",
            "message_id": mid,
            "labels": ["received"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "from": args.sender,
            "to": [args.inbox],
            "subject": args.subject,
            "text": args.text,
            "extracted_text": args.text,
            "in_reply_to": args.in_reply_to,
            "references": [args.in_reply_to] if args.in_reply_to else [],
            "attachments": [],
            "size": len(args.text),
        },
        "thread": {"inbox_id": args.inbox, "thread_id": args.thread, "message_count": 2},
    }
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if args.secret:
        svix_id = f"msg_{uuid.uuid4().hex[:16]}"
        ts = str(int(time.time()))
        headers.update({
            "svix-id": svix_id,
            "svix-timestamp": ts,
            "svix-signature": sign_payload(args.secret, svix_id, ts, body),
        })

    import httpx

    resp = httpx.post(args.url, content=body, headers=headers, timeout=30.0)
    print(f"{resp.status_code} {resp.text.strip()}  (message_id={mid})")
    return 0 if resp.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
