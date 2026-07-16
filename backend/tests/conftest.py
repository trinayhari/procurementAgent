"""Shared test fixtures.

SAFETY: provider credentials are force-blanked BEFORE the app is imported so
tests can never hit real Google Maps, Gmail, or OpenAI — even when a developer
has live keys in backend/.env (environment variables take precedence over the
dotenv file in pydantic-settings). Every external call in tests goes through
the mock providers.
"""
import os
import tempfile

# Must happen before any `app.*` import anywhere in the test session.
os.environ.update(
    {
        "PROCUREAI_GOOGLE_MAPS_API_KEY": "",
        "PROCUREAI_GMAIL_CLIENT_ID": "",
        "PROCUREAI_GMAIL_CLIENT_SECRET": "",
        "PROCUREAI_GMAIL_REFRESH_TOKEN": "",
        "PROCUREAI_GMAIL_SENDER_ADDRESS": "",
        "PROCUREAI_OPENAI_API_KEY": "",
        "PROCUREAI_OPENAI_BASE_URL": "",
        "PROCUREAI_SEED_DEMO_DATA": "false",
        "PROCUREAI_ENV": "development",
        "PROCUREAI_DATABASE_URL": "sqlite:///" + tempfile.mktemp(suffix="-test.db"),
        "PROCUREAI_UPLOAD_DIR": tempfile.mkdtemp(prefix="procureai-test-uploads-"),
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402


def _assert_mocked() -> None:
    assert not settings.google_maps_api_key
    assert not settings.gmail_refresh_token
    assert not settings.openai_api_key


_assert_mocked()


@pytest.fixture()
def client():
    """A TestClient on a FRESH database (schema via init_db, per test)."""
    from app import models  # noqa: F401
    from app.core import ratelimit
    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    ratelimit._hits.clear()  # each test gets a fresh rate-limit window
    with TestClient(app) as c:  # runs startup (init_db etc.)
        yield c


@pytest.fixture()
def auth(client):
    """(client, headers) for a registered user."""
    r = client.post(
        "/api/auth/register",
        json={"email": "pm@example.com", "password": "password123", "name": "PM"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["accessToken"]
    return client, {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def project(auth):
    """(client, headers, project_id)."""
    client, headers = auth
    r = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "Test Project", "loc": "Austin, TX", "type": "Commercial"},
    )
    assert r.status_code == 201, r.text
    return client, headers, r.json()["id"]


def make_confirmed_bom(client, headers, project_id, name="Hydrants Package"):
    """Create + confirm a custom BOM with two priced-quantity lines; returns its id."""
    r = client.post(
        "/api/documents/manual", headers=headers, json={"name": name, "projectId": project_id}
    )
    assert r.status_code == 201, r.text
    bom_id = r.json()["id"]
    r = client.put(
        f"/api/documents/{bom_id}/line-items",
        headers=headers,
        json={
            "groups": [
                {
                    "group": name,
                    "count": 2,
                    "tone": "blue",
                    "items": [
                        {"n": "Fire hydrant", "q": "5 EA"},
                        {"n": "8-inch gate valve", "q": "9 EA"},
                    ],
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/documents/{bom_id}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    return bom_id


def run_supplier_search(client, headers, project_id, package, radius=75):
    """Kick off a (mock) supplier search and return the found-supplier ids."""
    r = client.post(
        f"/api/projects/{project_id}/packages/{package}/search-suppliers",
        headers=headers,
        json={"radius_mi": radius},
    )
    assert r.status_code == 202, r.text
    r = client.get(
        f"/api/projects/{project_id}/suppliers/found?package={package}", headers=headers
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "done", data
    return [s["id"] for tier in data["tiers"] for s in tier["suppliers"]]


def generate_rfq(client, headers, project_id, package, supplier_ids):
    r = client.post(
        f"/api/projects/{project_id}/packages/{package}/rfqs/generate",
        headers=headers,
        json={"supplier_ids": supplier_ids},
    )
    assert r.status_code == 201, r.text
    return r.json()
