"""Email sender behind a small interface.

AgentMailSender sends from the organization's agent inbox through the AgentMail
API (client.inboxes.messages.send for a new conversation, messages.reply to
stay in an existing thread). When the API key isn't configured, get_sender()
returns a MockSender that only logs, so the "send" step works end-to-end
offline.

Sender identity (important):
  Everything an organization sends goes out from ITS agent inbox (for example
  acme@proq.tryproq.dev, see services/email/agentmail_client.py). A user's own
  address is never the From: it is carried in the display name we record for
  audit ("Jane Doe: Acme" <acme@proq.tryproq.dev>) and as a Cc so the buyer
  keeps a copy. See from_header() / resolve_cc() below.
"""
import base64
import logging
import mimetypes
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import formataddr, parseaddr
from typing import List, Optional, Protocol

from sqlalchemy.orm import Session

from app.config import settings
from app.services.email import agentmail_client

logger = logging.getLogger("procureai.rfq.sender")

# Stand-in shown when an organization has no agent inbox yet (the key is unset,
# so nothing can be delivered and get_sender() returns MockSender). It is not
# a real mailbox, so never present it as a working From address: email_config()
# reports `inboxAddress: null` and the UI labels it as unconfigured.
UNCONFIGURED_SENDER_ADDRESS = "rfq@procureai.local"

# Total attachment budget per email. AgentMail caps an inline request at 6 MB
# after base64 (~37% inflation), so 4 MB of source files keeps the encoded
# request inside. Enforced here (before any API call) as well as at RFQ
# save/send time in the route.
MAX_ATTACHMENT_TOTAL_BYTES = 4 * 1024 * 1024

# Responses worth one more try: rate limiting and transient server errors.
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_RETRY_DELAYS_S = (1.0, 3.0)


class EmailUnavailable(Exception):
    """Raised when email cannot be sent (missing creds / deps / provider error).

    The message is written for the person reading it in the UI (per-recipient
    send status, the Settings test-email result, an award notice failure), see
    describe_error(). `retryable` says whether trying again later is likely to
    help (rate limit / 5xx) as opposed to a broken configuration.
    """

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _http_status(exc: Exception) -> Optional[int]:
    """The HTTP status of an SDK ApiError (or None)."""
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "resp", None)
        status = getattr(resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _error_body_text(exc: Exception) -> str:
    """AgentMail error bodies carry `message` (and often `fix`); prefer those
    to the SDK's `headers: ..., status_code: ..., body: ...` repr."""
    body = getattr(exc, "body", None)
    if body is None:
        return ""
    msg = getattr(body, "message", None)
    fix = getattr(body, "fix", None)
    if isinstance(body, dict):
        msg = body.get("message")
        fix = body.get("fix")
    parts = [str(p).strip() for p in (msg, fix) if p]
    return " ".join(parts)


def describe_error(exc: Exception, *, stage: str = "send") -> str:
    """A one-line, human-readable reason for a failed AgentMail call."""
    status = _http_status(exc)
    detail = _error_body_text(exc)
    raw = detail or str(exc) or exc.__class__.__name__
    low = raw.lower()
    if status == 401 or "unauthorized" in low or "invalid api key" in low:
        return (
            "AgentMail rejected the API key (HTTP 401): check "
            "PROCUREAI_AGENTMAIL_API_KEY (docs/email-setup.md)."
        )
    if status == 429 or "rate limit" in low or "too many requests" in low:
        return "AgentMail is rate limiting this organization (HTTP 429): wait a minute and retry."
    if status == 413 or "entity too large" in low:
        return "The email (with attachments) is over AgentMail's 6 MB request limit: remove some files."
    if status is not None and status >= 500:
        return f"AgentMail is temporarily unavailable (HTTP {status}): retry in a few minutes."
    if status in (400, 422) and ("recipient" in low or "address" in low or "email" in low):
        return f"AgentMail rejected the recipient address: {raw}"
    if status == 403:
        return f"AgentMail refused the request (HTTP 403): {raw}"
    if status == 404:
        return f"AgentMail could not find the inbox or message (HTTP 404): {raw}"
    if "name or service not known" in low or "connection" in low or "timed out" in low:
        return "Could not reach AgentMail (network error): check connectivity and retry."
    tail = raw.strip().replace("\n", " ")
    if len(tail) > 200:
        tail = tail[:197] + "..."
    return f"AgentMail {stage} failed: {tail}"


# Last real AgentMail outcome, for Settings (GET /api/auth/email-config →
# agentmail): "configured" only says the key is set; this says whether the
# API actually answered the last time we called it.
_STATE: dict = {"error": None, "at": None, "ok_at": None}


def record_failure(message: str) -> None:
    _STATE["error"] = message
    _STATE["at"] = datetime.now(timezone.utc).isoformat()


def record_success() -> None:
    _STATE["error"] = None
    _STATE["at"] = None
    _STATE["ok_at"] = datetime.now(timezone.utc).isoformat()


def reset_state() -> None:
    _STATE.update({"error": None, "at": None, "ok_at": None})


def provider_status() -> dict:
    return {
        "lastError": _STATE["error"],
        "lastErrorAt": _STATE["at"],
        "lastOkAt": _STATE["ok_at"],
    }


def _retryable(exc: Exception) -> bool:
    status = _http_status(exc)
    if status in _RETRYABLE_HTTP:
        return True
    low = str(exc).lower()
    return "rate limit" in low or "too many requests" in low


@dataclass
class EmailAttachment:
    """A file to attach to an outbound email, already loaded into memory.

    Bytes (not a path/locator) so the send path is storage-agnostic: the route
    hydrates each document once via storage.local_copy() and reuses the same
    list for every recipient.
    """

    filename: str
    content: bytes
    mime_type: Optional[str] = None


@dataclass
class SentMessage:
    """Identifiers AgentMail returns for a sent message.

    `thread_id` is the attribution key for replies: a supplier's answer lands
    in the same thread and the webhook row carries that id. `message_id` is
    what a later reply from us passes as `in_reply_to`.
    """

    message_id: str
    thread_id: str


class EmailSender(Protocol):
    mocked: bool

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        from_addr: str,
        cc: Optional[str] = None,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        reply_to: Optional[str] = None,
    ) -> SentMessage:
        """Send one email and return its AgentMail message + thread ids.

        `from_addr` is informational (the inbox is always the From); it is
        kept so callers can record the identity they sent as.

        `cc` keeps the buyer who triggered the send in the loop (User.cc_email);
        it is dropped when it would duplicate `to` or `from_addr` (see resolve_cc).

        `in_reply_to` (an AgentMail message id) makes the email a reply in that
        message's thread, e.g. an award notice in the supplier's original RFQ
        conversation; `thread_id` is accepted for callers that only stored
        that and is informational here.

        `attachments` are project documents the user chose to include (already
        loaded into memory); when absent the message is a plain-text email.
        """
        ...


def _addr_only(value: str) -> str:
    """'Jane <a@b.com>' → 'a@b.com' (lowercased); '' when there's no address."""
    return parseaddr(value or "")[1].strip().lower()


def resolve_cc(cc: Optional[str], to: str, from_addr: str) -> Optional[str]:
    """The `Cc:` to actually set, or None.

    Drops a Cc that is already receiving the message (the recipient, or the
    inbox we send from, which keeps its own copy) so nobody gets the same email
    twice.
    """
    if not _addr_only(cc or ""):
        return None
    if _addr_only(cc) in {_addr_only(to), _addr_only(from_addr)}:
        return None
    return (cc or "").strip()


def _clean_header(value: str) -> str:
    """Strip control characters (CR/LF above all) from a header value.

    Subject and attachment filenames carry user-influenced text (trade names,
    edited subjects, upload names); an embedded CRLF must never reach a mail
    header.
    """
    return "".join(c for c in (value or "") if c.isprintable() or c == " ").strip()


def build_attachments(attachments: Optional[List[EmailAttachment]]) -> List[dict]:
    """The `attachments` payload for messages.send / reply: base64 content,
    a cleaned filename and a MIME type guessed from it when not given."""
    out: List[dict] = []
    for att in attachments or []:
        # Filenames derive from user-controlled upload names; strip control
        # characters so a crafted name can't inject mail headers through
        # Content-Disposition.
        filename = _clean_header(att.filename) or "attachment"
        mime_type = att.mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        out.append({
            "filename": filename,
            "content_type": mime_type,
            "content": base64.b64encode(att.content).decode(),
        })
    return out


class MockSender:
    mocked = True
    # Not a real mailbox (see UNCONFIGURED_SENDER_ADDRESS).
    address = UNCONFIGURED_SENDER_ADDRESS

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        from_addr: str,
        cc: Optional[str] = None,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        reply_to: Optional[str] = None,
    ) -> SentMessage:
        mid = f"mock-{uuid.uuid4().hex[:12]}"
        att_desc = (
            ", ".join(f"{a.filename} ({len(a.content)}b)" for a in attachments)
            if attachments
            else "-"
        )
        logger.info(
            "[MOCK SEND] id=%s from=%s to=%s cc=%s subject=%r thread=%s reply_to=%s (%d chars) attachments=%s",
            mid, from_addr, to, resolve_cc(cc, to, from_addr) or "-", subject,
            thread_id or "-", in_reply_to or "-", len(body), att_desc,
        )
        return SentMessage(message_id=mid, thread_id=thread_id or mid)


class AgentMailSender:
    """Sends from one organization's agent inbox."""

    mocked = False

    def __init__(self, inbox_id: str):
        self.inbox_id = inbox_id

    @property
    def address(self) -> str:
        """The inbox id is the address (acme@proq.tryproq.dev)."""
        return self.inbox_id

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        from_addr: str,
        cc: Optional[str] = None,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        reply_to: Optional[str] = None,
    ) -> SentMessage:
        # Fail fast, before touching the API, on things it would reject (or
        # accept and deliver as a blank email).
        if "@" not in _addr_only(to):
            raise EmailUnavailable(f"No valid recipient address: {to!r}")
        if not (subject or "").strip():
            raise EmailUnavailable("Email subject is empty: nothing was sent.")
        if not (body or "").strip():
            raise EmailUnavailable("Email body is empty: nothing was sent.")
        total_bytes = sum(len(a.content) for a in (attachments or []))
        if total_bytes > MAX_ATTACHMENT_TOTAL_BYTES:
            limit_mb = MAX_ATTACHMENT_TOTAL_BYTES // (1024 * 1024)
            raise EmailUnavailable(
                f"Attachments total {total_bytes / (1024 * 1024):.1f} MB, over the "
                f"{limit_mb} MB email limit; remove some files."
            )
        cc_addr = resolve_cc(cc, to, self.inbox_id)
        # No Reply-To unless a caller asks for one. Supplier replies must come
        # back to the agent inbox: that is where the webhook delivers them and
        # what attributes a reply to its RFQ. The buyer stays in the loop via Cc.
        payload: dict = {"text": body}
        if cc_addr:
            payload["cc"] = [cc_addr]
        if attachments:
            payload["attachments"] = build_attachments(attachments)
        if reply_to:
            payload["reply_to"] = reply_to
        client = agentmail_client.get_client()
        if in_reply_to and not str(in_reply_to).startswith(("mock", "error")):
            # messages.reply keeps the thread and sets In-Reply-To/References
            # for us; the recipient is the original sender of that message.
            call = lambda: client.inboxes.messages.reply(  # noqa: E731
                self.inbox_id, in_reply_to, to=[to], **payload
            )
        else:
            call = lambda: client.inboxes.messages.send(  # noqa: E731
                self.inbox_id, to=[to], subject=_clean_header(subject), **payload
            )
        sent = self._execute(call)
        message_id = getattr(sent, "message_id", "") or ""
        return SentMessage(
            message_id=message_id,
            thread_id=getattr(sent, "thread_id", "") or thread_id or message_id,
        )

    def _execute(self, call):
        """One API call with a short retry on rate limits / 5xx."""
        attempt = 0
        while True:
            try:
                sent = call()
                record_success()
                return sent
            except Exception as exc:
                if _retryable(exc) and attempt < len(_RETRY_DELAYS_S):
                    delay = _RETRY_DELAYS_S[attempt]
                    attempt += 1
                    logger.warning(
                        "AgentMail send attempt %d failed (%s); retrying in %.0fs",
                        attempt, exc, delay,
                    )
                    time.sleep(delay)
                    continue
                message = describe_error(exc)
                record_failure(message)
                raise EmailUnavailable(message, retryable=_retryable(exc)) from exc


def probe_email(db: Session, org_id: str) -> dict:
    """Actually talk to AgentMail: make sure the org's inbox exists and read it
    back. Reports the inbox address and whether the API answered. Never raises."""
    out = {"ok": False, "error": None, "inboxAddress": None}
    missing = missing_config()
    if missing:
        out["error"] = "Not configured: missing " + ", ".join(missing)
        return out
    from app.repositories import organizations as organizations_repo

    org = organizations_repo.get_organization(db, org_id)
    if org is None:
        out["error"] = "Organization not found"
        return out
    try:
        inbox_id = agentmail_client.ensure_inbox(db, org)
        inbox = agentmail_client.get_client().inboxes.get(inbox_id)
        out["inboxAddress"] = getattr(inbox, "inbox_id", None) or inbox_id
        out["ok"] = True
        record_success()
    except Exception as exc:
        out["error"] = describe_error(exc, stage="inbox check")
        record_failure(out["error"])
    return out


# The env var that makes real delivery possible.
_REQUIRED_VARS = (("PROCUREAI_AGENTMAIL_API_KEY", "agentmail_api_key"),)


def missing_config() -> List[str]:
    """Names of the PROCUREAI_AGENTMAIL_* variables that are unset (empty → all set)."""
    return [
        env for env, attr in _REQUIRED_VARS
        if not (getattr(settings, attr, "") or "").strip()
    ]


def is_configured() -> bool:
    """True when the AgentMail API key is set (real sends possible).

    Missing → MockSender (logged, not delivered) and the UI says so. Reads
    app.config.settings, which loads apps/api/.env and is overridden by real
    environment variables (Railway/Render service vars). See docs/email-setup.md.
    """
    return not missing_config()


def get_sender(db: Session, org_id: str) -> EmailSender:
    """AgentMail from this organization's agent inbox if configured, else a
    logging mock. Creates the inbox on first use."""
    if not is_configured():
        return MockSender()
    from app.repositories import organizations as organizations_repo

    org = organizations_repo.get_organization(db, org_id)
    if org is None:
        raise EmailUnavailable(f"Organization {org_id!r} not found")
    try:
        inbox_id = agentmail_client.ensure_inbox(db, org)
    except EmailUnavailable:
        raise
    except Exception as exc:
        message = describe_error(exc, stage="inbox create")
        record_failure(message)
        raise EmailUnavailable(message, retryable=_retryable(exc)) from exc
    return AgentMailSender(inbox_id)


def sender_address(db: Optional[Session] = None, org_id: Optional[str] = None) -> str:
    """The mailbox this organization's outbound email is sent from: its agent
    inbox once it exists. Falls back to UNCONFIGURED_SENDER_ADDRESS (not a real
    mailbox) before then; callers that show it to a human should pair it with
    email_config()["inboxAddress"] so a placeholder is never displayed as if
    it were live.
    """
    if db is not None and org_id:
        addr = agentmail_client.inbox_address(db, org_id)
        if addr:
            return addr
    return UNCONFIGURED_SENDER_ADDRESS


def display_name(user) -> str:
    """'Jane Doe: Acme Construction' from a user, skipping missing parts.

    Empty when the account has neither a name nor a company; from_header() then
    sends the bare address rather than an empty label.
    """
    name = (getattr(user, "name", "") or "").strip()
    company = (getattr(user, "company", "") or "").strip()
    return ": ".join(part for part in (name, company) if part)


def from_header(user=None, address: Optional[str] = None) -> str:
    """The identity mail this user triggers is recorded as.

    The address is ALWAYS the organization's agent inbox (`address`, normally
    `sender.address`; the placeholder before the inbox exists); only the
    display name is personalised, e.g. `"Jane Doe: Acme" <acme@proq.tryproq.dev>`.
    A user's own address is never used here: supplier replies have to return
    to the inbox the webhook reads. Users are Cc'd instead (User.cc_email).
    """
    addr = address or UNCONFIGURED_SENDER_ADDRESS
    label = display_name(user) if user is not None else ""
    # formataddr quotes/RFC2047-encodes the label so commas and quotes can't
    # corrupt the header.
    return formataddr((label, addr)) if label else addr


def from_display(user=None, address: Optional[str] = None) -> str:
    """The identity from_header() builds, unencoded, for showing to a human.

    from_header() RFC2047-encodes a non-ASCII display name, correct on the
    wire but unreadable in the UI or an audit entry. Both name the same
    mailbox; use this one only for display, never as a header value.
    """
    addr = address or UNCONFIGURED_SENDER_ADDRESS
    label = display_name(user) if user is not None else ""
    return "{} <{}>".format(label, addr) if label else addr


def email_config(db: Optional[Session] = None, org_id: Optional[str] = None) -> dict:
    """What outbound email will actually do right now.

    Surfaced by GET /api/auth/email-config so the UI can say "not configured"
    instead of implying mail is going out. `inboxAddress` is the org's agent
    inbox, or null before it has been created.
    """
    missing = missing_config()
    configured = not missing
    address = agentmail_client.inbox_address(db, org_id) if (db is not None and org_id) else None
    return {
        "configured": configured,
        "mocked": not configured,
        "inboxAddress": address,
        # Which PROCUREAI_AGENTMAIL_* variables are still unset, so Settings
        # can name the actual gap instead of a generic "not configured".
        "missing": missing,
        # Whether the API actually answered the last time we used it.
        "agentmail": provider_status(),
    }
