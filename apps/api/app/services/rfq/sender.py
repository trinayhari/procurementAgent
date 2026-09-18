"""Email sender behind a small interface.

GmailSender uses a stored OAuth2 refresh token to call the Gmail API
(users.messages.send). When Gmail creds aren't configured, get_sender() returns a
MockSender that only logs — so the "send" step works end-to-end offline.

Sender identity (important):
  Everything goes out from ONE mailbox — the connected Gmail account named by
  PROCUREAI_GMAIL_SENDER_ADDRESS. A user's own address is never used in `From:`;
  it is carried as the display name (`"Jane Doe — Acme" <bids@ours.com>`) and as
  a `Cc:` so the buyer keeps a copy. See from_header() / resolve_cc() below.
"""
import base64
import logging
import mimetypes
import time
import uuid
from dataclasses import dataclass
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from typing import List, Optional, Protocol

from app.config import settings

logger = logging.getLogger("procureai.rfq.sender")

# Outbound RFQs only. The quote-ingest reader requests gmail.readonly separately
# (see gmail_reader._READ_SCOPES). Refreshing with a subset of the token's granted
# scopes is fine, so keeping send isolated here means a send-only token still works.
_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Stand-in used ONLY when PROCUREAI_GMAIL_SENDER_ADDRESS is unset — which also
# means nothing can be delivered (get_sender() returns MockSender). It is not a
# real mailbox, so never present it as a working From address: email_config()
# reports `senderAddressSet: false` and the UI labels it as unconfigured.
UNCONFIGURED_SENDER_ADDRESS = "rfq@procureai.local"

# Total attachment budget per email. Gmail's nominal limit is 25 MB, but the
# raw payload is base64 (~37% inflation) and large JSON `{"raw": ...}` sends via
# the google-api-python-client are unreliable well below that — 15 MB of source
# files keeps the encoded message comfortably inside. Enforced here (before any
# Gmail call) as well as at RFQ save/send time in the route.
MAX_ATTACHMENT_TOTAL_BYTES = 15 * 1024 * 1024

# Gmail responses worth one more try: rate limiting and transient server errors.
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_RETRY_DELAYS_S = (1.0, 3.0)


class GmailUnavailable(Exception):
    """Raised when the Gmail API cannot be called (missing creds / deps / error).

    The message is written for the person reading it in the UI (per-recipient
    send status, the Settings test-email result, an award notice failure) —
    see describe_gmail_error(). `retryable` says whether trying again later is
    likely to help (rate limit / 5xx) as opposed to a broken configuration.
    """

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _http_status(exc: Exception) -> Optional[int]:
    """The HTTP status of a googleapiclient HttpError (or None)."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def describe_gmail_error(exc: Exception, *, stage: str = "send") -> str:
    """A one-line, human-readable reason for a failed Gmail call.

    Raw google-auth / googleapiclient errors read like
    `('invalid_grant: Token has been expired or revoked.', {'error': ...})` or
    `<HttpError 429 when requesting ... returned "User-rate limit exceeded">`.
    Neither tells a buyer what to do; the strings here do.
    """
    raw = str(exc) or exc.__class__.__name__
    low = raw.lower()
    if "invalid_grant" in low or "token has been expired" in low or "token has been revoked" in low:
        return (
            "Gmail connection expired or was revoked (invalid_grant) — re-mint the "
            "refresh token (docs/email-setup.md, Step 3) and restart the backend."
        )
    if "invalid_client" in low or "unauthorized_client" in low:
        return (
            "Gmail OAuth client id/secret were rejected (invalid_client) — check "
            "PROCUREAI_GMAIL_CLIENT_ID / PROCUREAI_GMAIL_CLIENT_SECRET."
        )
    if "invalid_scope" in low or "insufficient" in low and "scope" in low:
        return (
            "The Gmail token lacks the required scope — re-mint it with "
            "scripts/mint_gmail_token.py (send + readonly)."
        )
    status = _http_status(exc)
    if status == 429 or "rate limit" in low or "ratelimit" in low or "quota" in low:
        return "Gmail is rate limiting this mailbox (HTTP 429) — wait a few minutes and retry."
    if status is not None and status >= 500:
        return f"Gmail is temporarily unavailable (HTTP {status}) — retry in a few minutes."
    if status == 400 and ("recipient" in low or "invalid to header" in low or "address" in low):
        return "Gmail rejected the recipient address — check the email and retry."
    if status == 401 or status == 403:
        return (
            f"Gmail refused the request (HTTP {status}) — the connected account "
            "may have revoked access; re-mint the token (docs/email-setup.md)."
        )
    if "name or service not known" in low or "connection" in low or "timed out" in low:
        return "Could not reach Gmail (network error) — check connectivity and retry."
    tail = raw.strip().replace("\n", " ")
    if len(tail) > 200:
        tail = tail[:197] + "..."
    return f"Gmail {stage} failed: {tail}"


# Last real Gmail outcome, for Settings (GET /api/auth/email-config → gmail):
# "configured" only says the four env vars are set; this says whether the
# mailbox actually answered the last time we called it.
_GMAIL_STATE: dict = {"error": None, "at": None, "ok_at": None}


def record_gmail_failure(message: str) -> None:
    from datetime import datetime, timezone

    _GMAIL_STATE["error"] = message
    _GMAIL_STATE["at"] = datetime.now(timezone.utc).isoformat()


def record_gmail_success() -> None:
    from datetime import datetime, timezone

    _GMAIL_STATE["error"] = None
    _GMAIL_STATE["at"] = None
    _GMAIL_STATE["ok_at"] = datetime.now(timezone.utc).isoformat()


def reset_gmail_state() -> None:
    _GMAIL_STATE.update({"error": None, "at": None, "ok_at": None})


def gmail_status() -> dict:
    return {
        "lastError": _GMAIL_STATE["error"],
        "lastErrorAt": _GMAIL_STATE["at"],
        "lastOkAt": _GMAIL_STATE["ok_at"],
    }


def _retryable(exc: Exception) -> bool:
    status = _http_status(exc)
    if status in _RETRYABLE_HTTP:
        return True
    low = str(exc).lower()
    return "rate limit" in low or "ratelimit" in low or "backend error" in low


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
    """Identifiers Gmail returns for a sent message.

    `thread_id` lets us later pull the whole conversation (supplier replies land
    in the same thread). For a first send Gmail returns thread_id == message_id.
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
    ) -> SentMessage:
        """Send one email and return its Gmail message + thread ids.

        `cc` keeps the buyer who triggered the send in the loop (User.cc_email);
        it is dropped when it would duplicate `to` or `from_addr` (see resolve_cc).

        `thread_id` (a Gmail thread id) and `in_reply_to` (the RFC822 Message-ID of
        the message being replied to) make the email land inside an existing thread
        — e.g. an award reply in the supplier's original RFQ conversation.

        `attachments` are project documents the user chose to include (already
        loaded into memory); when absent the message is a plain-text email.
        """
        ...


def _addr_only(value: str) -> str:
    """'Jane <a@b.com>' → 'a@b.com' (lowercased); '' when there's no address."""
    return parseaddr(value or "")[1].strip().lower()


def resolve_cc(cc: Optional[str], to: str, from_addr: str) -> Optional[str]:
    """The `Cc:` to actually set, or None.

    Drops a Cc that is already receiving the message — the recipient, or the
    workspace mailbox we send from (which keeps its own copy in Sent) — so nobody
    gets the same email twice.
    """
    if not _addr_only(cc or ""):
        return None
    if _addr_only(cc) in {_addr_only(to), _addr_only(from_addr)}:
        return None
    return (cc or "").strip()


def _clean_header(value: str) -> str:
    """Strip control characters (CR/LF above all) from a header value.

    Subject, To, and Cc all carry user-influenced text (trade names, edited
    subjects, recipient emails) and compat32 does not validate header values —
    an embedded CRLF would inject arbitrary headers into the raw Gmail send.
    """
    return "".join(c for c in (value or "") if c.isprintable() or c == " ").strip()


def _build_mime(
    to: str,
    subject: str,
    body: str,
    from_addr: str,
    *,
    cc: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    attachments: Optional[List[EmailAttachment]] = None,
) -> str:
    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body))
        for att in attachments:
            # Filenames derive from user-controlled upload names; strip control
            # characters so a crafted name can't inject mail headers through
            # Content-Disposition.
            filename = _clean_header(att.filename) or "attachment"
            mime_type = att.mime_type or mimetypes.guess_type(filename)[0]
            maintype, _, subtype = (mime_type or "application/octet-stream").partition("/")
            part = MIMEBase(maintype, subtype or "octet-stream")
            part.set_payload(att.content)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", "attachment", filename=filename
            )
            msg.attach(part)
    else:
        # No attachments → keep the historical plain-text shape byte-for-byte.
        msg = MIMEText(body)
    msg["To"] = _clean_header(to)
    msg["From"] = from_addr
    cc = resolve_cc(cc, to, from_addr)
    if cc:
        msg["Cc"] = _clean_header(cc)
    msg["Subject"] = _clean_header(subject)
    if in_reply_to:
        # Both headers so replying clients (and Gmail) thread it under the RFQ.
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    # DELIBERATELY no Reply-To header. Supplier replies must come back to the
    # connected mailbox: that inbox is what quote ingest reads
    # (services/quotes/gmail_reader.py) and what services/rfq/conversation.py
    # rebuilds an RFQ thread from. Pointing Reply-To at the buyer's own address
    # would route replies somewhere we never read and silently break both. The
    # buyer stays in the loop via Cc instead — do not "fix" this.
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


class MockSender:
    mocked = True

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
    ) -> SentMessage:
        mid = f"mock-{uuid.uuid4().hex[:12]}"
        att_desc = (
            ", ".join(f"{a.filename} ({len(a.content)}b)" for a in attachments)
            if attachments
            else "-"
        )
        logger.info(
            "[MOCK SEND] id=%s from=%s to=%s cc=%s subject=%r thread=%s (%d chars) attachments=%s",
            mid, from_addr, to, resolve_cc(cc, to, from_addr) or "-", subject,
            thread_id or "-", len(body), att_desc,
        )
        return SentMessage(message_id=mid, thread_id=thread_id or mid)


class GmailSender:
    mocked = False

    def __init__(self):
        # One token refresh per sender instance (an RFQ send to N suppliers used
        # to refresh the token N times — and hit the token endpoint N times when
        # the refresh token was dead).
        self._svc = None

    def _service(self):
        if self._svc is not None:
            return self._svc
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise GmailUnavailable("google api client packages are not installed") from exc

        creds = Credentials(
            token=None,
            refresh_token=settings.gmail_refresh_token,
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            token_uri=_TOKEN_URI,
            scopes=_GMAIL_SCOPES,
        )
        try:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
        except Exception as exc:
            message = describe_gmail_error(exc, stage="token refresh")
            record_gmail_failure(message)
            raise GmailUnavailable(message, retryable=_retryable(exc)) from exc
        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._svc

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
    ) -> SentMessage:
        # Fail fast, before touching Gmail, on things Gmail would reject (or
        # accept and deliver as a blank email).
        if "@" not in _addr_only(to):
            raise GmailUnavailable(f"No valid recipient address: {to!r}")
        if not (subject or "").strip():
            raise GmailUnavailable("Email subject is empty — nothing was sent.")
        if not (body or "").strip():
            raise GmailUnavailable("Email body is empty — nothing was sent.")
        total_bytes = sum(len(a.content) for a in (attachments or []))
        if total_bytes > MAX_ATTACHMENT_TOTAL_BYTES:
            limit_mb = MAX_ATTACHMENT_TOTAL_BYTES // (1024 * 1024)
            raise GmailUnavailable(
                f"Attachments total {total_bytes / (1024 * 1024):.1f} MB — over the "
                f"{limit_mb} MB email limit; remove some files."
            )
        service = self._service()
        # Gmail delivers to every address in the headers, so a Cc: header is all
        # that's needed to copy the buyer.
        raw = _build_mime(
            to, subject, body, from_addr,
            cc=cc, in_reply_to=in_reply_to, attachments=attachments,
        )
        message: dict = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        sent = self._execute_send(service, message)
        return SentMessage(
            message_id=sent.get("id", ""),
            thread_id=sent.get("threadId", "") or sent.get("id", ""),
        )

    def _execute_send(self, service, message: dict) -> dict:
        """messages.send with a short retry on rate limits / 5xx."""
        attempt = 0
        while True:
            try:
                sent = (
                    service.users()
                    .messages()
                    .send(userId="me", body=message)
                    .execute()
                )
                record_gmail_success()
                return sent
            except Exception as exc:
                if _retryable(exc) and attempt < len(_RETRY_DELAYS_S):
                    delay = _RETRY_DELAYS_S[attempt]
                    attempt += 1
                    logger.warning(
                        "Gmail send attempt %d failed (%s); retrying in %.0fs",
                        attempt, exc, delay,
                    )
                    time.sleep(delay)
                    continue
                message = describe_gmail_error(exc)
                record_gmail_failure(message)
                raise GmailUnavailable(message, retryable=_retryable(exc)) from exc


def probe_gmail() -> dict:
    """Actually talk to Gmail: refresh the send-scope token and read the
    mailbox profile with the read scope. Reports which side failed and whether
    the mailbox is the one PROCUREAI_GMAIL_SENDER_ADDRESS names. Never raises."""
    out = {
        "ok": False, "error": None, "emailAddress": None, "senderAddress": sender_address(),
        "senderAddressMatches": None, "sendScope": False, "readScope": False,
    }
    missing = missing_config()
    if missing:
        out["error"] = "Not configured — missing " + ", ".join(missing)
        return out
    try:
        GmailSender()._service()
        out["sendScope"] = True
    except GmailUnavailable as exc:
        out["error"] = str(exc)
        return out
    try:
        from app.services.quotes import gmail_reader

        gmail_reader.reset_service_cache()
        profile = gmail_reader._service().users().getProfile(userId="me").execute()
        out["readScope"] = True
        addr = (profile.get("emailAddress") or "").strip().lower()
        out["emailAddress"] = addr or None
        out["senderAddressMatches"] = bool(addr) and addr == sender_address().lower()
        if addr and not out["senderAddressMatches"]:
            out["error"] = (
                f"The connected mailbox is {addr} but PROCUREAI_GMAIL_SENDER_ADDRESS is "
                f"{sender_address()} — Gmail will rewrite From: to the connected account; set the variable to {addr}."
            )
    except Exception as exc:
        out["error"] = describe_gmail_error(exc, stage="read")
        return out
    out["ok"] = out["error"] is None
    if out["ok"]:
        record_gmail_success()
    else:
        record_gmail_failure(out["error"])
    return out


# The four env vars that together make real delivery possible.
_REQUIRED_VARS = (
    ("PROCUREAI_GMAIL_CLIENT_ID", "gmail_client_id"),
    ("PROCUREAI_GMAIL_CLIENT_SECRET", "gmail_client_secret"),
    ("PROCUREAI_GMAIL_REFRESH_TOKEN", "gmail_refresh_token"),
    ("PROCUREAI_GMAIL_SENDER_ADDRESS", "gmail_sender_address"),
)


def missing_config() -> List[str]:
    """Names of the PROCUREAI_GMAIL_* variables that are unset (empty → all set)."""
    return [
        env for env, attr in _REQUIRED_VARS
        if not (getattr(settings, attr, "") or "").strip()
    ]


def is_configured() -> bool:
    """True when all four PROCUREAI_GMAIL_* vars are set (real sends possible).

    The three OAuth vars are what Gmail needs; the sender address is required
    too because without it every message would carry the placeholder
    UNCONFIGURED_SENDER_ADDRESS as `From:` — Gmail rewrites that to the
    connected account, so mail *would* go out, but the app could not say from
    where, and email_config() would be lying either way. Missing any of the
    four → MockSender (logged, not delivered) and the UI says so.

    Reads app.config.settings, which loads apps/api/.env and is overridden by real
    environment variables (Railway/Render service vars). See docs/email-setup.md.
    """
    return not missing_config()


def get_sender() -> EmailSender:
    """Gmail if configured, else a logging mock."""
    if is_configured():
        return GmailSender()
    return MockSender()


def sender_address() -> str:
    """The single mailbox every outbound email is sent from.

    Always PROCUREAI_GMAIL_SENDER_ADDRESS — the account the Gmail API token
    belongs to. Falls back to UNCONFIGURED_SENDER_ADDRESS (not a real mailbox)
    when that var is unset; callers that show it to a human should pair it with
    email_config()["senderAddressSet"] so a placeholder is never displayed as if
    it were live.
    """
    return (settings.gmail_sender_address or "").strip() or UNCONFIGURED_SENDER_ADDRESS


def display_name(user) -> str:
    """'Jane Doe — Acme Construction' from a user, skipping missing parts.

    Empty when the account has neither a name nor a company — from_header() then
    sends the bare address rather than an empty label.
    """
    name = (getattr(user, "name", "") or "").strip()
    company = (getattr(user, "company", "") or "").strip()
    return " — ".join(part for part in (name, company) if part)


def from_header(user=None) -> str:
    """The `From:` header for mail this user triggers.

    The address is ALWAYS the workspace mailbox (sender_address()); only the
    display name is personalised, e.g. `"Jane Doe — Acme" <bids@ours.com>`.
    A user's own address is never used here: Gmail rewrites an unverified From
    back to the connected account anyway, and supplier replies have to return to
    the mailbox quote ingest reads. Users are Cc'd instead (User.cc_email).
    """
    addr = sender_address()
    label = display_name(user) if user is not None else ""
    # formataddr quotes/RFC2047-encodes the label so commas, quotes and the em
    # dash can't corrupt the header.
    return formataddr((label, addr)) if label else addr


def from_display(user=None) -> str:
    """The identity from_header() builds, unencoded, for showing to a human.

    from_header() RFC2047-encodes a non-ASCII display name (the em dash in
    "Jane Doe — Acme" becomes `=?utf-8?q?...?=`) — correct on the wire, but
    unreadable in the UI or an audit entry. Both name the same mailbox; use this
    one only for display, never as a header value.
    """
    addr = sender_address()
    label = display_name(user) if user is not None else ""
    return "{} <{}>".format(label, addr) if label else addr


def email_config() -> dict:
    """What outbound email will actually do right now — all driven by env vars.

    Surfaced by GET /api/auth/email-config so the UI can say "not configured"
    instead of showing the placeholder From address as if mail were going out.
    """
    missing = missing_config()
    configured = not missing
    return {
        "configured": configured,
        "mocked": not configured,
        "senderAddressSet": bool((settings.gmail_sender_address or "").strip()),
        "fromAddress": sender_address(),
        # Which PROCUREAI_GMAIL_* variables are still unset — so Settings can
        # name the actual gap instead of a generic "not configured".
        "missing": missing,
        # Whether the mailbox actually answered the last time we used it.
        "gmail": gmail_status(),
    }
