"""Email sender behind a small interface.

GmailSender uses a stored OAuth2 refresh token to call the Gmail API
(users.messages.send). When Gmail creds aren't configured, get_sender() returns a
MockSender that only logs — so the "send" step works end-to-end offline.
"""
import base64
import logging
import uuid
from email.mime.text import MIMEText
from typing import Protocol

from app.config import settings

logger = logging.getLogger("procureai.rfq.sender")

_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailUnavailable(Exception):
    """Raised when the Gmail API cannot be called (missing creds / deps / error)."""


class EmailSender(Protocol):
    mocked: bool

    def send(self, to: str, subject: str, body: str, *, from_addr: str) -> str:
        """Send one email and return a message id."""
        ...


def _build_mime(to: str, subject: str, body: str, from_addr: str) -> str:
    msg = MIMEText(body)
    msg["To"] = to
    msg["From"] = from_addr
    msg["Subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


class MockSender:
    mocked = True

    def send(self, to: str, subject: str, body: str, *, from_addr: str) -> str:
        mid = f"mock-{uuid.uuid4().hex[:12]}"
        logger.info(
            "[MOCK SEND] id=%s from=%s to=%s subject=%r (%d chars)",
            mid, from_addr, to, subject, len(body),
        )
        return mid


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

    def send(self, to: str, subject: str, body: str, *, from_addr: str) -> str:
        service = self._service()
        raw = _build_mime(to, subject, body, from_addr)
        try:
            sent = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
        except Exception as exc:
            raise GmailUnavailable(f"Gmail send failed: {exc}") from exc
        return sent.get("id", "")


def is_configured() -> bool:
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
    return settings.gmail_sender_address or "rfq@procureai.local"
