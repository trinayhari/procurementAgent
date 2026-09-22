"""AgentMail client and the per-organization agent inbox.

Every customer organization gets its own inbox in AgentMail (for example
acme@proq.tryproq.dev), created the first time the org needs to send or
receive mail and stored on Organization.agentmail_inbox_id. The inbox id IS
the address. That address is the agent's identity for the customer: the PM
emails it, suppliers receive RFQs from it and reply to it.

All AgentMail I/O funnels through get_client() so tests can swap the SDK for a
fake with one monkeypatch (the API key is blank under tests and nothing here
is ever called for real).
"""
import base64
import hashlib
import hmac
import logging
import re
import time
import uuid
from typing import Mapping, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.organization import Organization

logger = logging.getLogger("procureai.email.agentmail")

# Svix rejects signatures older than five minutes; mirror that here.
_TIMESTAMP_TOLERANCE_S = 5 * 60

_client = None
_client_key: Optional[str] = None

# Local development without an API key: an organization still needs an address
# the forged webhook (scripts/send_test_inbound.py) can be posted to, so the
# mock sender assigns "<org slug>@mock.proq.local" on first use and the
# webhook resolves that address back to the org. Never in production, and a
# real key ignores a stored mock address (ensure_inbox creates the real one).
MOCK_INBOX_DOMAIN = "mock.proq.local"


def is_configured() -> bool:
    """True when an AgentMail API key is set (real sends and inboxes)."""
    return bool((settings.agentmail_api_key or "").strip())


def get_client():
    """The SDK client, built once per API key. Tests monkeypatch this."""
    global _client, _client_key
    key = (settings.agentmail_api_key or "").strip()
    if not key:
        raise RuntimeError("PROCUREAI_AGENTMAIL_API_KEY is not set")
    if _client is None or _client_key != key:
        from agentmail import AgentMail

        _client = AgentMail(api_key=key)
        _client_key = key
    return _client


def reset_client() -> None:
    global _client, _client_key
    _client = None
    _client_key = None


# ------------------------------------------------------------------ inboxes
def _slug(value: str) -> str:
    """'Acme Construction, LLC' -> 'acme-construction-llc' (a valid local part)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:40].strip("-") or "org"


def _is_taken(exc: Exception) -> bool:
    """The username is already in use (AgentMail answers 403 IsTaken or 409)."""
    status = getattr(exc, "status_code", None)
    if status in (403, 409):
        return True
    return "taken" in str(exc).lower()


def _create_inbox(client, **fields):
    """inboxes.create, pod-scoped when settings.agentmail_pod_id is set.

    The org-level SDK method takes a CreateInboxRequest object; the pod one
    takes keyword arguments. Both return an Inbox with `inbox_id`.
    """
    pod_id = (settings.agentmail_pod_id or "").strip()
    if pod_id:
        return client.pods.inboxes.create(pod_id, **fields)
    from agentmail.inboxes.types import CreateInboxRequest

    return client.inboxes.create(request=CreateInboxRequest(**fields))


def is_mock_inbox(inbox_id: Optional[str]) -> bool:
    """True for the development stand-in address (see MOCK_INBOX_DOMAIN)."""
    return bool(inbox_id) and str(inbox_id).lower().endswith("@" + MOCK_INBOX_DOMAIN)


def mock_inboxes_allowed() -> bool:
    """Mock addresses exist only while no key is set and outside production."""
    return not is_configured() and settings.env != "production"


def mock_inbox_id(org: Organization) -> str:
    return f"{_slug(org.name)}@{MOCK_INBOX_DOMAIN}"


def ensure_mock_inbox(db: Session, org: Organization) -> Optional[str]:
    """Development without AgentMail: give the org its deterministic mock
    address on first use so a forged delivery can be routed to it. Returns
    None (and stores nothing) when mock inboxes are not allowed."""
    if not mock_inboxes_allowed():
        return None
    if org.agentmail_inbox_id:
        return org.agentmail_inbox_id
    org.agentmail_inbox_id = mock_inbox_id(org)
    db.add(org)
    db.commit()
    logger.info("Assigned mock agent inbox %s to organization %s (no AgentMail key)", org.agentmail_inbox_id, org.id)
    return org.agentmail_inbox_id


def ensure_inbox(db: Session, org: Organization) -> str:
    """The org's agent inbox id (its address), creating the inbox on first use.

    username = a slug of the org name, with a short suffix when that address is
    already taken; domain = settings.agentmail_domain (or AgentMail's default
    when empty); client_id = the org id so a retried create is idempotent.
    A mock address left over from development is replaced by a real inbox.
    """
    if org.agentmail_inbox_id and not is_mock_inbox(org.agentmail_inbox_id):
        return org.agentmail_inbox_id
    client = get_client()
    base = _slug(org.name)
    display_name = f"{settings.agentmail_display_name_prefix} {org.name}".strip()
    fields = {
        "display_name": display_name,
        "client_id": org.id,
        "metadata": {"organization_id": org.id},
    }
    domain = (settings.agentmail_domain or "").strip()
    if domain:
        fields["domain"] = domain
    username = base
    inbox = None
    for attempt in range(4):
        try:
            inbox = _create_inbox(client, username=username, **fields)
            break
        except Exception as exc:
            if attempt < 3 and _is_taken(exc):
                username = f"{base}-{uuid.uuid4().hex[:4]}"
                continue
            raise
    inbox_id = getattr(inbox, "inbox_id", None) or getattr(inbox, "email", None)
    if not inbox_id:
        raise RuntimeError("AgentMail returned an inbox without an id")
    org.agentmail_inbox_id = inbox_id
    db.add(org)
    db.commit()
    logger.info("Created agent inbox %s for organization %s", inbox_id, org.id)
    return inbox_id


def inbox_address(db: Session, org_id: str) -> Optional[str]:
    """The org's agent inbox address, or None before the inbox exists."""
    org = db.get(Organization, org_id)
    return org.agentmail_inbox_id if org is not None else None


def org_for_inbox(db: Session, inbox_id: str) -> Optional[Organization]:
    """Which organization owns an AgentMail inbox (None for an unknown inbox).

    In development without a key, "<slug>@mock.proq.local" resolves to the
    org whose name slugs to that local part (and is stored on it, so the
    address stays stable), which lets a forged delivery reach an org that has
    never sent anything. Production only ever matches a stored inbox id.
    """
    if not inbox_id:
        return None
    org = db.scalars(
        select(Organization).where(Organization.agentmail_inbox_id == inbox_id)
    ).first()
    if org is not None or not (is_mock_inbox(inbox_id) and mock_inboxes_allowed()):
        return org
    wanted = str(inbox_id).lower()
    for candidate in db.scalars(
        select(Organization).where(Organization.agentmail_inbox_id.is_(None))
    ):
        if mock_inbox_id(candidate) == wanted:
            candidate.agentmail_inbox_id = wanted
            db.add(candidate)
            db.commit()
            logger.info("Assigned mock agent inbox %s to organization %s (no AgentMail key)", wanted, candidate.id)
            return candidate
    return None


# ----------------------------------------------------------- Svix signing
def _secret_bytes(secret: str) -> bytes:
    raw = (secret or "").strip()
    if raw.startswith("whsec_"):
        raw = raw[len("whsec_"):]
    return base64.b64decode(raw)


def sign_payload(secret: str, msg_id: str, timestamp: str, body: bytes) -> str:
    """The `v1,<base64>` signature Svix computes for a delivery (also used by
    scripts/send_test_inbound.py to forge a local delivery)."""
    to_sign = f"{msg_id}.{timestamp}.".encode() + body
    digest = hmac.new(_secret_bytes(secret), to_sign, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def verify_svix(secret: str, headers: Mapping[str, str], body: bytes,
                *, now: Optional[float] = None) -> bool:
    """Check a Svix-signed webhook delivery.

    Headers `svix-id`, `svix-timestamp` and `svix-signature` (a space-separated
    list of `v1,<base64>` values); the signature is HMAC-SHA256 over
    "{id}.{timestamp}.{body}" keyed with the base64-decoded secret after
    `whsec_`. A timestamp more than five minutes off is rejected.
    """
    if not secret:
        return False
    lowered = {str(k).lower(): v for k, v in headers.items()}
    msg_id = lowered.get("svix-id", "")
    timestamp = lowered.get("svix-timestamp", "")
    signatures = lowered.get("svix-signature", "")
    if not (msg_id and timestamp and signatures):
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - ts) > _TIMESTAMP_TOLERANCE_S:
        return False
    try:
        expected = sign_payload(secret, msg_id, timestamp, body)
    except Exception:
        return False
    for candidate in signatures.split():
        if not candidate.startswith("v1,"):
            continue
        if hmac.compare_digest(candidate, expected):
            return True
    return False
