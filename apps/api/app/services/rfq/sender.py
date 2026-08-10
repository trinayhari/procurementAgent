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


class GmailUnavailable(Exception):
    """Raised when the Gmail API cannot be called (missing creds / deps / error)."""


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
            mime_type = att.mime_type or mimetypes.guess_type(att.filename)[0]
            maintype, _, subtype = (mime_type or "application/octet-stream").partition("/")
            part = MIMEBase(maintype, subtype or "octet-stream")
            part.set_payload(att.content)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", "attachment", filename=att.filename
            )
            msg.attach(part)
    else:
        # No attachments → keep the historical plain-text shape byte-for-byte.
        msg = MIMEText(body)
    msg["To"] = to
    msg["From"] = from_addr
    cc = resolve_cc(cc, to, from_addr)
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
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

    def _service(self):
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
            raise GmailUnavailable(f"Gmail token refresh failed: {exc}") from exc
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

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
        try:
            sent = (
                service.users()
                .messages()
                .send(userId="me", body=message)
                .execute()
            )
        except Exception as exc:
            raise GmailUnavailable(f"Gmail send failed: {exc}") from exc
        return SentMessage(
            message_id=sent.get("id", ""),
            thread_id=sent.get("threadId", "") or sent.get("id", ""),
        )


def is_configured() -> bool:
    """True when the three PROCUREAI_GMAIL_* OAuth vars are all set (real sends).

    Reads app.config.settings, which loads apps/api/.env and is overridden by real
    environment variables (Railway/Render service vars). See docs/email-setup.md.
    """
    return bool(
        settings.gmail_refresh_token
        and settings.gmail_client_id
        and settings.gmail_client_secret
    )


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
    return settings.gmail_sender_address or UNCONFIGURED_SENDER_ADDRESS


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
    configured = is_configured()
    return {
        "configured": configured,
        "mocked": not configured,
        "senderAddressSet": bool(settings.gmail_sender_address),
        "fromAddress": sender_address(),
    }
