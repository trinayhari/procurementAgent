"""Read supplier quote replies from Gmail (gmail.readonly).

Confines all inbound Gmail I/O here, mirroring sender.py. Returns plain inbound
messages (id, from, subject, combined text of body + any PDF attachments). When
Gmail isn't configured, callers fall back to the deterministic mock in ingest.py.
"""
import base64
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import settings
from app.services.rfq.sender import _TOKEN_URI, is_configured

logger = logging.getLogger("procureai.quotes.gmail")

# Read scope only. The refresh token must have been granted this scope (re-mint
# with scripts/mint_gmail_token.py, which now requests send + readonly). A
# send-only token will fail refresh here with invalid_scope → signal to re-auth.
_READ_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailReadUnavailable(Exception):
    """Raised when the Gmail read API cannot be called."""


@dataclass
class InboundMessage:
    message_id: str
    from_email: str
    subject: str
    text: str
    attachments_text: List[str] = field(default_factory=list)

    @property
    def combined_text(self) -> str:
        return "\n\n".join([self.text, *self.attachments_text]).strip()


@dataclass
class ThreadEmail:
    """One message in a Gmail conversation, shaped for display (not parsing)."""

    message_id: str
    thread_id: str
    from_email: str
    from_name: str
    subject: str
    date_ms: int
    text: str
    attachments: List[str] = field(default_factory=list)  # attachment filenames


def _service():
    if not is_configured():
        raise GmailReadUnavailable("Gmail credentials are not configured")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise GmailReadUnavailable("google api client packages are not installed") from exc

    creds = Credentials(
        token=None,
        refresh_token=settings.gmail_refresh_token,
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        token_uri=_TOKEN_URI,
        scopes=_READ_SCOPES,
    )
    try:
        creds.refresh(Request())
    except Exception as exc:
        raise GmailReadUnavailable(
            "Gmail read access failed — re-mint the token with the gmail.readonly "
            f"scope (scripts/mint_gmail_token.py). Detail: {exc}"
        ) from exc
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _pdf_to_text(data: bytes) -> str:
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as doc:
            return " ".join(page.get_text() for page in doc)
    except Exception:
        return ""


def _walk(service, msg_id: str, payload: dict, out_text: List[str], out_attach: List[str]) -> None:
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mime == "text/plain" and body.get("data"):
        out_text.append(base64.urlsafe_b64decode(body["data"]).decode("utf-8", "ignore"))
    elif mime == "application/pdf" or (payload.get("filename", "").lower().endswith(".pdf")):
        att_id = body.get("attachmentId")
        if att_id:
            try:
                att = service.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=att_id
                ).execute()
                data = base64.urlsafe_b64decode(att["data"])
                text = _pdf_to_text(data)
                if text:
                    out_attach.append(text)
            except Exception:
                pass
    for part in payload.get("parts", []) or []:
        _walk(service, msg_id, part, out_text, out_attach)


def fetch_replies(sender_emails: List[str], lookback_days: int = 30, limit: int = 50) -> List[InboundMessage]:
    """Inbound messages from any of `sender_emails` within the lookback window."""
    if not sender_emails:
        return []
    service = _service()
    from_clause = " OR ".join(f"from:{e}" for e in sender_emails)
    query = f"({from_clause}) newer_than:{lookback_days}d"
    try:
        listing = service.users().messages().list(
            userId="me", q=query, maxResults=limit
        ).execute()
    except Exception as exc:
        raise GmailReadUnavailable(f"Gmail list failed: {exc}") from exc

    out: List[InboundMessage] = []
    for ref in listing.get("messages", []) or []:
        mid = ref.get("id")
        if not mid:
            continue
        try:
            full = service.users().messages().get(userId="me", id=mid, format="full").execute()
        except Exception:
            continue
        payload = full.get("payload", {})
        text_parts: List[str] = []
        attach_parts: List[str] = []
        _walk(service, mid, payload, text_parts, attach_parts)
        from_email = _parse_addr(_header(payload, "From"))
        out.append(
            InboundMessage(
                message_id=mid,
                from_email=from_email,
                subject=_header(payload, "Subject"),
                text="\n".join(text_parts).strip() or full.get("snippet", ""),
                attachments_text=attach_parts,
            )
        )
    return out


def _parse_addr(raw: str) -> str:
    """'Sales <a@b.com>' → 'a@b.com'."""
    raw = raw or ""
    if "<" in raw and ">" in raw:
        return raw[raw.index("<") + 1 : raw.index(">")].strip().lower()
    return raw.strip().lower()


def _parse_name(raw: str) -> str:
    """'Sales <a@b.com>' → 'Sales' (falls back to the address)."""
    raw = (raw or "").strip()
    if "<" in raw:
        name = raw[: raw.index("<")].strip().strip('"')
        if name:
            return name
    return _parse_addr(raw)


def _strip_quoted(text: str) -> str:
    """Drop the quoted reply chain so each message shows only its new content."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out: List[str] = []
    for ln in lines:
        s = ln.strip()
        # Common reply/forward markers Gmail/Outlook prepend to the prior message.
        if s.startswith(">") or s.startswith("On ") and s.endswith("wrote:"):
            break
        if s.startswith("-----Original Message-----") or s.startswith("________"):
            break
        out.append(ln)
    return "\n".join(out).strip()


def _body_and_attachments(payload: dict) -> tuple:
    """(plain-text body, [attachment filenames]) from a Gmail message payload."""
    texts: List[str] = []
    files: List[str] = []

    def walk(p: dict) -> None:
        fname = p.get("filename") or ""
        body = p.get("body", {})
        if fname:
            files.append(fname)
        elif p.get("mimeType") == "text/plain" and body.get("data"):
            texts.append(base64.urlsafe_b64decode(body["data"]).decode("utf-8", "ignore"))
        for part in p.get("parts", []) or []:
            walk(part)

    walk(payload)
    return "\n".join(texts).strip(), files


def resolve_thread_id(message_id: str) -> Optional[str]:
    """Look up the Gmail thread a sent message belongs to (for older sends that
    were stored before we captured threadId)."""
    if not message_id or message_id.startswith(("error", "mock")):
        return None
    service = _service()
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="metadata"
        ).execute()
    except Exception:
        return None
    return msg.get("threadId")


def rfc822_message_id(message_id: str) -> Optional[str]:
    """The RFC822 `Message-ID` header of a sent Gmail message, for threading a
    reply (In-Reply-To/References). Best-effort — returns None if unavailable."""
    if not message_id or message_id.startswith(("error", "mock")):
        return None
    service = _service()
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="metadata", metadataHeaders=["Message-ID"]
        ).execute()
    except Exception:
        return None
    return _header(msg.get("payload", {}), "Message-ID") or None


def _thread_email_from_message(m: dict) -> ThreadEmail:
    """Build a display ThreadEmail from a full Gmail message resource."""
    payload = m.get("payload", {})
    body, files = _body_and_attachments(payload)
    body = _strip_quoted(body) or (m.get("snippet", "") or "")
    try:
        date_ms = int(m.get("internalDate", "0"))
    except (TypeError, ValueError):
        date_ms = 0
    raw_from = _header(payload, "From")
    return ThreadEmail(
        message_id=m.get("id", ""),
        thread_id=m.get("threadId", ""),
        from_email=_parse_addr(raw_from),
        from_name=_parse_name(raw_from),
        subject=_header(payload, "Subject"),
        date_ms=date_ms,
        text=body,
        attachments=files,
    )


def fetch_thread(thread_id: str) -> List[ThreadEmail]:
    """Every message in a Gmail conversation, oldest first."""
    if not thread_id:
        return []
    service = _service()
    try:
        data = service.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute()
    except Exception as exc:
        raise GmailReadUnavailable(f"Gmail thread fetch failed: {exc}") from exc

    out = [_thread_email_from_message(m) for m in data.get("messages", []) or []]
    out.sort(key=lambda e: e.date_ms)
    return out
