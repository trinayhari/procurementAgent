"""AgentMail webhook (public; Svix signature-verified). Mounted without auth in
main.py.

One organization-level webhook in AgentMail posts every `message.received`
event for every agent inbox here. The route:

1. verifies the Svix signature (skipped only when the secret is empty AND the
   app is not in production; production with no secret answers 503);
2. maps `message.inbox_id` to the organization that owns the inbox (unknown
   inbox: 200, logged, dropped, so AgentMail stops retrying);
3. downloads each attachment through the API into services/storage;
4. stores an InboundEmail row (idempotent on the AgentMail message id);
5. hands the row to services.inbound.handle in a background task, which
   never fails the response (a processing error is recorded on the row).
"""
import base64
import json
import logging
import os
import re
import tempfile
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import SessionLocal
from app.models.inbound_email import InboundEmail
from app.repositories import inbound_emails as inbound_repo
from app.services import storage
from app.services.email import agentmail_client
from app.services.email import text as email_text

logger = logging.getLogger("procureai.webhooks.agentmail")

router = APIRouter(prefix="/api/webhooks/agentmail", tags=["webhooks"])

_HANDLED_EVENTS = {"message.received", "message.received.unauthenticated"}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = _SAFE_NAME_RE.sub("_", base).strip("._")
    return base or "attachment"


def _inline_content(att: dict) -> Optional[bytes]:
    """Attachment bytes carried inline as base64 `content` (a forged local
    delivery from scripts/send_test_inbound.py); None when absent."""
    raw = att.get("content")
    if not raw or not isinstance(raw, str):
        return None
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, TypeError):
        return None


def _download(client, inbox_id: str, message_id: str, attachment_id: str) -> Optional[bytes]:
    """The attachment bytes: the SDK answers with a short-lived download URL."""
    import httpx

    if client is None:
        logger.warning("Attachment %s of %s skipped: no AgentMail key to download it", attachment_id, message_id)
        return None
    info = client.inboxes.messages.get_attachment(inbox_id, message_id, attachment_id)
    if isinstance(info, (bytes, bytearray)):
        return bytes(info)
    url = getattr(info, "download_url", None)
    if not url:
        return None
    resp = httpx.get(url, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _store_attachments(inbox_id: str, message: dict) -> List[dict]:
    """Persist each attachment through services/storage; a failed download is
    logged and skipped so one bad file never loses the message."""
    out: List[dict] = []
    attachments = message.get("attachments") or []
    if not attachments:
        return out
    # No key (development): inline content still works, API downloads are skipped.
    client = agentmail_client.get_client() if agentmail_client.is_configured() else None
    for att in attachments:
        att_id = att.get("attachment_id")
        filename = _safe_filename(att.get("filename") or att_id or "attachment")
        try:
            data = _inline_content(att)
            if data is None:
                data = _download(client, inbox_id, message.get("message_id", ""), att_id)
            if data is None:
                continue
            fd, tmp_path = tempfile.mkstemp(prefix="procureai-inbound-", suffix=os.path.splitext(filename)[1])
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            stored = storage.persist_temp(
                storage.StoredFile(locator=tmp_path, sha256="", size=len(data)), filename
            )
        except Exception:
            logger.warning("Could not store attachment %s of %s", att_id, message.get("message_id"), exc_info=True)
            continue
        out.append({
            "filename": att.get("filename") or filename,
            "mimeType": att.get("content_type") or "",
            "size": stored.size,
            "locator": stored.locator,
        })
    return out


def _addresses(values) -> List[str]:
    if isinstance(values, str):
        values = [values]
    return [str(v) for v in (values or []) if v]


def _row_fields(org_id: str, message: dict, attachments: List[dict]) -> dict:
    headers = message.get("headers") or {}
    raw_from = message.get("from") or ""
    references = message.get("references") or []
    if isinstance(references, str):
        references = references.split()
    return {
        "organization_id": org_id,
        "provider_message_id": message.get("message_id") or "",
        "inbox_id": message.get("inbox_id") or "",
        "thread_id": message.get("thread_id") or "",
        "rfc_message_id": headers.get("message-id") or headers.get("Message-ID") or message.get("message_id") or "",
        "in_reply_to": message.get("in_reply_to") or headers.get("in-reply-to") or "",
        "references": " ".join(references),
        "from_email": email_text.parse_addr(raw_from),
        "from_name": email_text.parse_name(raw_from),
        "to_addresses": _addresses(message.get("to")),
        "cc_addresses": _addresses(message.get("cc")),
        "subject": message.get("subject") or "",
        "text": message.get("extracted_text") or message.get("text") or "",
        "html": message.get("html") or "",
        "attachments": attachments,
    }


def _process(row_id: str) -> None:
    """Background: attribute + handle the stored row; errors land on the row."""
    from app.services import inbound

    db = SessionLocal()
    try:
        row = db.get(InboundEmail, row_id)
        if row is None:
            return
        try:
            inbound.handle(db, row)
        except Exception as exc:
            logger.exception("Inbound email %s failed to process", row_id)
            db.rollback()
            row = db.get(InboundEmail, row_id)
            if row is not None:
                inbound_repo.mark_failed(db, row, str(exc) or exc.__class__.__name__)
    finally:
        db.close()


@router.post("", status_code=200)
async def receive(request: Request, background: BackgroundTasks) -> Response:
    body = await request.body()
    secret = (settings.agentmail_webhook_secret or "").strip()
    if secret:
        if not agentmail_client.verify_svix(secret, request.headers, body):
            return Response(status_code=401, content="invalid signature")
    elif settings.env == "production":
        logger.error("AgentMail webhook received but PROCUREAI_AGENTMAIL_WEBHOOK_SECRET is empty; refusing")
        return Response(status_code=503, content="webhook secret not configured")
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return Response(status_code=400, content="invalid json")
    event_type = payload.get("event_type") or payload.get("type")
    if event_type not in _HANDLED_EVENTS:
        return Response(status_code=200, content="ignored")
    message = payload.get("message") or {}
    provider_id = message.get("message_id") or ""
    inbox_id = message.get("inbox_id") or ""
    if not provider_id or not inbox_id:
        return Response(status_code=400, content="message_id and inbox_id are required")

    db = SessionLocal()
    try:
        if inbound_repo.get_by_provider_id(db, provider_id) is not None:
            return Response(status_code=200, content="duplicate")
        org = agentmail_client.org_for_inbox(db, inbox_id)
        if org is None:
            logger.warning("AgentMail message %s for unknown inbox %s dropped", provider_id, inbox_id)
            return Response(status_code=200, content="unknown inbox")
        attachments = _store_attachments(inbox_id, message)
        try:
            row = inbound_repo.create(db, **_row_fields(org.id, message, attachments))
        except IntegrityError:
            # Two deliveries of the same event raced past the lookup above;
            # the unique index on provider_message_id keeps one row.
            db.rollback()
            return Response(status_code=200, content="duplicate")
        row_id = row.id
    finally:
        db.close()
    background.add_task(_process, row_id)
    return Response(status_code=200, content="stored")
