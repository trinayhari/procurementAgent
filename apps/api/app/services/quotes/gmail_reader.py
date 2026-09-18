"""Read supplier quote replies from Gmail (gmail.readonly).

Confines all inbound Gmail I/O here, mirroring sender.py. Returns plain inbound
messages (id, from, subject, combined text of body + any PDF attachments). When
Gmail isn't configured, callers fall back to the deterministic mock in ingest.py.
"""
import base64
import html
import logging
import re
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import List, Optional

from app.config import settings
from app.services.quotes import pdf_text
from app.services.rfq.sender import (
    _TOKEN_URI,
    describe_gmail_error,
    is_configured,
    record_gmail_failure,
    record_gmail_success,
)

logger = logging.getLogger("procureai.quotes.gmail")

# Read scope only. The refresh token must have been granted this scope (re-mint
# with scripts/mint_gmail_token.py, which now requests send + readonly). A
# send-only token will fail refresh here with invalid_scope → signal to re-auth.
_READ_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailReadUnavailable(Exception):
    """Raised when the Gmail read API cannot be called."""


# One authorised client per credential set: the conversation view used to
# refresh the OAuth token once per recipient on every open, and ingest once
# per thread. google-auth refreshes the access token itself when it expires,
# so the built service stays valid across calls.
_SERVICE_CACHE: dict = {}


def _cache_key() -> tuple:
    return (settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token)


def reset_service_cache() -> None:
    _SERVICE_CACHE.clear()


@dataclass
class InboundMessage:
    message_id: str
    from_email: str
    subject: str
    text: str
    attachments_text: List[str] = field(default_factory=list)
    # Gmail thread the reply landed in — the send recorded the thread id per
    # recipient, so this attributes a reply to the right RFQ when a supplier
    # was asked to quote several packages.
    thread_id: str = ""
    # Gmail internalDate (ms since epoch) — ingest walks replies oldest-first so
    # a supplier's latest revision is the one that ends up current.
    date_ms: int = 0
    # Gmail label ids ("SENT", "INBOX", …). A message we sent ourselves carries
    # SENT; ingest also skips known outbound ids explicitly.
    label_ids: List[str] = field(default_factory=list)

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
    key = _cache_key()
    cached = _SERVICE_CACHE.get(key)
    if cached is not None:
        return cached
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
        message = describe_gmail_error(exc, stage="read")
        record_gmail_failure(message)
        raise GmailReadUnavailable(message) from exc
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    _SERVICE_CACHE.clear()
    _SERVICE_CACHE[key] = service
    return service


def _header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _pdf_to_text(data: bytes) -> str:
    """Text layer of a PDF attachment, parsed in a child process so a malformed
    file can't take the API down (PyMuPDF faults natively). "" on failure."""
    return pdf_text.extract(data)


_BR_RE = re.compile(r"<\s*br\s*/?>|</\s*(p|div|tr|li|h[1-6]|blockquote)\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_RE = re.compile(r"<\s*(style|script|head)[^>]*>.*?</\s*\1\s*>", re.I | re.S)
_BLOCKQUOTE_RE = re.compile(r"<\s*blockquote[^>]*>.*", re.I | re.S)


def html_to_text(markup: str) -> str:
    """A readable plain-text rendering of an HTML-only email body.

    Outlook, Apple Mail and many CRMs send HTML with no text/plain alternative;
    left as-is the conversation view showed raw tags (or only the snippet) and
    the quote parser saw nothing. Block-level closers become newlines, the
    quoted chain in a <blockquote> is dropped, entities are unescaped.
    """
    if not markup:
        return ""
    text = _STYLE_RE.sub("", markup)
    # Gmail wraps the quoted history in <blockquote class="gmail_quote">; Apple
    # Mail uses a plain <blockquote>. Everything from the first one on is the
    # prior conversation, not this message.
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _BR_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    out: List[str] = []
    blank = 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def _decode_part(body: dict) -> str:
    data = body.get("data")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
    except Exception:
        return ""


def _walk(service, msg_id: str, payload: dict, out_text: List[str], out_attach: List[str],
          out_html: Optional[List[str]] = None) -> None:
    mime = (payload.get("mimeType") or "").lower()
    body = payload.get("body", {}) or {}
    filename = payload.get("filename") or ""
    if mime == "text/plain" and body.get("data") and not filename:
        out_text.append(_decode_part(body))
    elif mime == "text/html" and body.get("data") and not filename:
        if out_html is not None:
            out_html.append(_decode_part(body))
    elif mime == "application/pdf" or filename.lower().endswith(".pdf"):
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
        _walk(service, msg_id, part, out_text, out_attach, out_html)


def _addr_set(addresses: List[str]) -> set:
    return {a for a in ((x or "").strip().lower() for x in addresses) if a}


def _gmail_from_clause(addresses: List[str]) -> str:
    """`from:a OR from:b` — each address quoted so `+` tags and dots survive."""
    return " OR ".join('from:"{}"'.format(a.replace('"', "")) for a in addresses)


def fetch_replies(sender_emails: List[str], lookback_days: int = 30, limit: int = 50,
                  skip_ids: Optional[set] = None) -> List[InboundMessage]:
    """Inbound messages from any of `sender_emails` within the lookback window.

    Gmail's `from:` operator matches loosely (a token of the address, so
    `from:sales@pipe.co` also finds sales@pipe.co.uk and sales@pipe.com); the
    result is filtered on the parsed From address so only exact matches come
    back. Oldest first, so a revised quote is processed after the original.
    """
    wanted = _addr_set(sender_emails)
    if not wanted:
        return []
    service = _service()
    lookback_days = max(1, int(lookback_days or 1))
    query = f"({_gmail_from_clause(sorted(wanted))}) newer_than:{lookback_days}d"
    try:
        listing = service.users().messages().list(
            userId="me", q=query, maxResults=limit
        ).execute()
    except Exception as exc:
        message = describe_gmail_error(exc, stage="list")
        record_gmail_failure(message)
        raise GmailReadUnavailable(message) from exc
    record_gmail_success()

    out: List[InboundMessage] = []
    for ref in listing.get("messages", []) or []:
        mid = ref.get("id")
        if not mid or (skip_ids and mid in skip_ids):
            continue  # already ingested / our own — don't download it again
        try:
            full = service.users().messages().get(userId="me", id=mid, format="full").execute()
        except Exception as exc:
            logger.warning("Gmail message %s could not be read: %s", mid, exc)
            continue
        msg = _inbound_from_full(service, full)
        if msg.from_email not in wanted:
            continue  # loose `from:` match — not one of this project's suppliers
        out.append(msg)
    out.sort(key=lambda m: m.date_ms)
    return out


def _inbound_from_full(service, full: dict) -> InboundMessage:
    """An InboundMessage (body + PDF attachment text) from a full Gmail message."""
    mid = full.get("id", "")
    payload = full.get("payload", {}) or {}
    text_parts: List[str] = []
    html_parts: List[str] = []
    attach_parts: List[str] = []
    _walk(service, mid, payload, text_parts, attach_parts, html_parts)
    # Parse only what the supplier wrote in THIS message. A reply carries the
    # quoted chain beneath it (our RFQ, or their earlier quote); left in, the
    # parser reads the old figures — the regex fallback takes the largest
    # dollar amount anywhere in the text, so a revised $47.5k quote on top of
    # a quoted $52k one came back as $52k.
    plain = "\n".join(p for p in text_parts if p.strip())
    if not plain.strip() and html_parts:
        plain = html_to_text("\n".join(html_parts))
    body = _strip_quoted(plain) or (full.get("snippet", "") or "")
    try:
        date_ms = int(full.get("internalDate", "0") or 0)
    except (TypeError, ValueError):
        date_ms = 0
    return InboundMessage(
        message_id=mid,
        from_email=_parse_addr(_header(payload, "From")),
        subject=_decode_rfc2047(_header(payload, "Subject")),
        text=body,
        attachments_text=attach_parts,
        thread_id=full.get("threadId", "") or "",
        date_ms=date_ms,
        label_ids=list(full.get("labelIds") or []),
    )


def fetch_thread_replies(thread_id: str, skip_ids: Optional[set] = None) -> List[InboundMessage]:
    """Every message in the Gmail thread an RFQ send created, oldest first,
    shaped for parsing (body + PDF attachment text).

    This is the primary way replies are found: a supplier who answers from a
    different address than the one we emailed (RFQ to sales@, quote from the
    estimator) is still in *our* thread. The caller drops our own messages.
    """
    if not thread_id:
        return []
    service = _service()
    try:
        data = service.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute()
    except Exception as exc:
        raise GmailReadUnavailable(describe_gmail_error(exc, stage="thread fetch")) from exc
    out = [
        _inbound_from_full(service, m)
        for m in data.get("messages", []) or []
        if not (skip_ids and m.get("id") in skip_ids)  # skip PDF downloads for known ids
    ]
    out.sort(key=lambda m: m.date_ms)
    return out


def _decode_rfc2047(value: str) -> str:
    """`=?utf-8?q?Jane_Doe_=E2=80=94_Acme?=` → `Jane Doe — Acme` (no-op otherwise)."""
    if not value or "=?" not in value:
        return value or ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _parse_addr(raw: str) -> str:
    """'Sales <a@b.com>' → 'a@b.com' (lower-cased; '' when there is none)."""
    return parseaddr(_decode_rfc2047(raw or ""))[1].strip().lower()


def _parse_name(raw: str) -> str:
    """'Sales <a@b.com>' → 'Sales' (falls back to the address)."""
    name, addr = parseaddr(_decode_rfc2047(raw or ""))
    name = (name or "").strip().strip('"').strip()
    return name or addr.strip().lower()


# Reply-chain markers, one per client family. Anything from the marker line on
# is the prior conversation, not this message.
_ON_WROTE_RE = re.compile(r"^(On|Le|Am|El|Il)\s.{0,300}?(wrote|a écrit|schrieb|escribió|ha scritto)\s*:\s*$", re.S)
_HEADER_BLOCK_START = re.compile(r"^(\*?\*?)(From|De|Von)\s*:\s*\*?\*?\s*\S", re.I)
_HEADER_BLOCK_NEXT = re.compile(r"^(\*?\*?)(Sent|To|Date|Subject|Cc|Envoyé|À|Gesendet|An)\s*:", re.I)
_SEPARATOR_RE = re.compile(r"^-{2,}\s*(Original Message|Forwarded message|Mensaje original|Message d'origine)\s*-{2,}\s*$", re.I)


def _strip_quoted(text: str) -> str:
    """Drop the quoted reply chain so each message shows only its new content.

    Handles the styles seen in practice:
      - Gmail / Apple Mail:  "On Tue, Sep 16, 2026 at 3:00 PM Jane <a@b> wrote:"
        (Gmail wraps the long form over two lines — the "wrote:" lands on the
        next line, so the marker is matched across up to three lines)
      - Outlook:             "-----Original Message-----" or a bare
        "From: … / Sent: … / To: … / Subject: …" header block, often preceded by
        a "________________________________" rule
      - Quoted lines:        "> …"
      - Localised variants of "On … wrote:" (fr/de/es/it).
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    stripped = [ln.strip() for ln in lines]
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        s = stripped[i]
        if s.startswith(">"):
            break
        if s.startswith("________"):
            break
        if _SEPARATOR_RE.match(s):
            break
        # "On … wrote:" possibly wrapped across 2–3 lines.
        if s.startswith(("On ", "Le ", "Am ", "El ", "Il ")) and any(
            _ON_WROTE_RE.match(" ".join(stripped[i:i + k])) for k in (1, 2, 3)
        ):
            break
        # Outlook-style header block: "From:" followed within 3 lines by Sent:/To:/Date:/Subject:.
        if _HEADER_BLOCK_START.match(s) and any(
            _HEADER_BLOCK_NEXT.match(x) for x in stripped[i + 1:i + 4]
        ):
            break
        out.append(lines[i])
        i += 1
    return "\n".join(out).strip()


def _body_and_attachments(payload: dict) -> tuple:
    """(plain-text body, [attachment filenames]) from a Gmail message payload."""
    texts: List[str] = []
    htmls: List[str] = []
    files: List[str] = []

    def walk(p: dict) -> None:
        fname = p.get("filename") or ""
        body = p.get("body", {}) or {}
        mime = (p.get("mimeType") or "").lower()
        if fname:
            files.append(fname)
        elif mime == "text/plain" and body.get("data"):
            texts.append(_decode_part(body))
        elif mime == "text/html" and body.get("data"):
            htmls.append(_decode_part(body))
        for part in p.get("parts", []) or []:
            walk(part)

    walk(payload)
    plain = "\n".join(t for t in texts if t.strip()).strip()
    if not plain and htmls:
        plain = html_to_text("\n".join(htmls))
    return plain, files


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
        subject=_decode_rfc2047(_header(payload, "Subject")),
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
        raise GmailReadUnavailable(describe_gmail_error(exc, stage="thread fetch")) from exc

    out = [_thread_email_from_message(m) for m in data.get("messages", []) or []]
    out.sort(key=lambda e: e.date_ms)
    return out
