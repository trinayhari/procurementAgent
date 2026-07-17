"""Auth flows, the auth wall on every route, rate limiting, token scoping."""
import re

from app.core import ratelimit
from app.core.security import create_scoped_token
from app.main import app


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
    # default From (no per-user sender set)
    r = client.post("/api/auth/test-email", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mocked"] is True
    assert data["to"] == "pm@example.com"
    assert data["messageId"].startswith("mock-")
    # per-user sender is used as the From address once set
    client.patch("/api/auth/me", headers=headers, json={"senderEmail": "bids@example.com"})
    r = client.post("/api/auth/test-email", headers=headers)
    assert r.json()["fromAddr"] == "bids@example.com"
