"""Auth flows, the auth wall on every route, rate limiting, token scoping."""
import re
from email.utils import parseaddr

from app.core import ratelimit
from app.core.security import create_scoped_token
from app.main import app
from app.services.rfq import sender as rfq_sender


def test_register_login_me(auth):
    client, headers = auth
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "pm@example.com"

    # wrong password
    r = client.post("/api/auth/login", json={"email": "pm@example.com", "password": "wrong-pass"})
    assert r.status_code == 401

    # duplicate email
    r = client.post(
        "/api/auth/register", json={"email": "pm@example.com", "password": "password123"}
    )
    assert r.status_code == 409

    # correct login
    r = client.post(
        "/api/auth/login", json={"email": "pm@example.com", "password": "password123"}
    )
    assert r.status_code == 200
    assert r.json()["accessToken"]


def test_demo_account_not_seeded(client):
    """The demo backdoor account must not exist unless demo seeding is enabled."""
    r = client.post(
        "/api/auth/login", json={"email": "jordan@meridiancivil.com", "password": "procureai"}
    )
    assert r.status_code == 401


def test_every_route_requires_auth(client):
    """Walk the app's routes: everything except the explicit public surface
    must reject an unauthenticated request with 401."""
    public = {
        ("/health", "GET"),
        ("/api/auth/login", "POST"),
        ("/api/auth/register", "POST"),
        # Signed-URL file serving authenticates via a scoped query token; it
        # must still reject requests without one (asserted separately below).
        ("/api/documents/{document_id}/file", "GET"),
    }
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not path.startswith(("/api", "/health")) or not methods:
            continue
        for method in methods - {"HEAD", "OPTIONS"}:
            if (path, method) in public:
                continue
            url = re.sub(r"{[^}]+}", "1", path)  # "1" satisfies str and int params
            r = client.request(method, url)
            assert r.status_code == 401, f"{method} {path} -> {r.status_code} (expected 401)"
            checked += 1
    assert checked > 25  # sanity: the wall actually covered the API surface


def test_file_route_rejects_missing_and_foreign_tokens(auth):
    client, headers = auth
    # no token
    assert client.get("/api/documents/some-doc/file").status_code == 401
    # token scoped to a DIFFERENT document
    token = create_scoped_token("other-doc", "file:other-doc", 5)
    assert client.get(f"/api/documents/some-doc/file?token={token}").status_code == 401


def test_scoped_token_is_not_an_api_token(client):
    """A signed file token must never work as a bearer token for the API."""
    token = create_scoped_token("some-doc", "file:some-doc", 5)
    r = client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_login_rate_limit(client):
    ratelimit._hits.clear()  # isolate from other tests sharing the process
    for _ in range(10):
        r = client.post("/api/auth/login", json={"email": "x@x.com", "password": "wrong-pass"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "x@x.com", "password": "wrong-pass"})
    assert r.status_code == 429
    ratelimit._hits.clear()


def test_send_test_email_mock(auth):
    """The config-verification endpoint works in mock mode and reports it."""
    client, headers = auth
    r = client.post("/api/auth/test-email", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mocked"] is True
    assert data["to"] == "pm@example.com"
    assert data["messageId"].startswith("mock-")
    # From is the workspace mailbox carrying the user's display name...
    assert parseaddr(data["fromAddr"])[1] == rfq_sender.sender_address()
    assert parseaddr(data["fromAddr"])[0] == "PM"
    # ...and the test goes to the user, so their Cc would duplicate it — dropped.
    assert data["cc"] is None

    # A Cc address that isn't the recipient does get copied.
    r = client.patch("/api/auth/me", headers=headers, json={"ccEmail": "bids@example.com"})
    assert r.json()["ccEmail"] == "bids@example.com"
    r = client.post("/api/auth/test-email", headers=headers)
    data = r.json()
    assert data["cc"] == "bids@example.com"
    # Setting a Cc must never change who the mail is from.
    assert parseaddr(data["fromAddr"])[1] == rfq_sender.sender_address()


def test_email_config_reports_unconfigured_gmail(auth):
    """The UI needs the truth: nothing is delivered and the address is a
    placeholder until PROCUREAI_GMAIL_* is set."""
    client, headers = auth
    r = client.get("/api/auth/email-config", headers=headers)
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["configured"] is False and cfg["mocked"] is True
    assert cfg["senderAddressSet"] is False
    assert cfg["fromAddress"] == rfq_sender.UNCONFIGURED_SENDER_ADDRESS
    assert cfg["ccEmail"] is None

    client.patch("/api/auth/me", headers=headers, json={"ccEmail": "bids@example.com"})
    assert client.get("/api/auth/email-config", headers=headers).json()["ccEmail"] == (
        "bids@example.com"
    )
