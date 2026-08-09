"""Team invite flow: invite → accept (join the inviting org) → revoke, plus the
rejection paths and cross-org isolation.

The invite's secret token is never returned by the API (it only travels in the
emailed link), so tests read it straight from the DB — standing in for the
invitee clicking the link. Provider creds are force-blanked by conftest, so the
invitation email goes through the MockSender and never leaves the process.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models.organization_invite import OrganizationInvite


def _register(client: TestClient, email: str, company: str) -> dict:
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "name": email.split("@")[0], "company": company},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


def _new_project(client: TestClient, headers: dict, name: str) -> str:
    r = client.post(
        "/api/projects", headers=headers,
        json={"name": name, "loc": "Austin, TX", "type": "Commercial"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _token_for(email: str) -> str:
    """The pending invite token for an email — what the emailed link carries."""
    with SessionLocal() as db:
        row = db.query(OrganizationInvite).filter(
            OrganizationInvite.email == email.lower()
        ).order_by(OrganizationInvite.seq.desc()).first()
        assert row is not None, f"no invite row for {email}"
        return row.token


@pytest.fixture()
def owner(client):
    """(client, headers) for a signed-in org owner."""
    return client, _register(client, "owner@alpha-gc.com", "Alpha GC")


# --------------------------------------------------------------------------- #
# Happy path: invite → preview → accept → teammates share one org.
# --------------------------------------------------------------------------- #

def test_invite_accept_puts_teammate_in_same_org(owner):
    client, headers = owner
    pid = _new_project(client, headers, "Shared Tower")

    # Owner invites a teammate.
    r = client.post("/api/team/invites", headers=headers, json={"email": "mate@alpha-gc.com"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "mate@alpha-gc.com"
    assert r.json()["status"] == "pending"
    assert "token" not in r.json()  # secret never leaves via the API

    # It shows up on the team page as a pending invite.
    team = client.get("/api/team", headers=headers).json()
    assert [m["email"] for m in team["members"]] == ["owner@alpha-gc.com"]
    assert [i["email"] for i in team["invites"]] == ["mate@alpha-gc.com"]

    # Invitee previews the link: valid, names the org and the email.
    token = _token_for("mate@alpha-gc.com")
    prev = client.get(f"/api/invite/{token}").json()
    assert prev == {"valid": True, "organizationName": "Alpha GC", "email": "mate@alpha-gc.com", "reason": None}

    # Invitee accepts with a password → gets logged in.
    r = client.post(f"/api/invite/{token}/accept", json={"name": "Mate", "password": "password123"})
    assert r.status_code == 201, r.text
    mate_token = r.json()["accessToken"]
    assert r.json()["user"]["email"] == "mate@alpha-gc.com"
    mate_headers = {"Authorization": f"Bearer {mate_token}"}

    # The teammate is in the SAME org: sees the owner's project.
    assert [p["name"] for p in client.get("/api/projects", headers=mate_headers).json()] == ["Shared Tower"]
    assert client.get("/api/auth/me", headers=mate_headers).json()["email"] == "mate@alpha-gc.com"

    # Owner and teammate now share the org id.
    assert (
        client.get("/api/auth/me", headers=headers).json()["organizationId"]
        == client.get("/api/auth/me", headers=mate_headers).json()["organizationId"]
    )

    # Team page now lists two members and no open invites.
    team = client.get("/api/team", headers=headers).json()
    assert {m["email"] for m in team["members"]} == {"owner@alpha-gc.com", "mate@alpha-gc.com"}
    assert team["invites"] == []


# --------------------------------------------------------------------------- #
# Rejection paths.
# --------------------------------------------------------------------------- #

def test_cannot_invite_an_existing_account(owner):
    client, headers = owner
    _register(client, "someone@other.com", "Other Co")
    r = client.post("/api/team/invites", headers=headers, json={"email": "someone@other.com"})
    assert r.status_code == 409, r.text


def test_duplicate_pending_invite_is_rejected(owner):
    client, headers = owner
    assert client.post("/api/team/invites", headers=headers, json={"email": "dup@alpha-gc.com"}).status_code == 201
    r = client.post("/api/team/invites", headers=headers, json={"email": "dup@alpha-gc.com"})
    assert r.status_code == 409, r.text


def test_revoked_invite_cannot_be_accepted(owner):
    client, headers = owner
    invite_id = client.post(
        "/api/team/invites", headers=headers, json={"email": "revoke@alpha-gc.com"}
    ).json()["id"]
    token = _token_for("revoke@alpha-gc.com")

    assert client.delete(f"/api/team/invites/{invite_id}", headers=headers).status_code == 204
    # Gone from the team page.
    assert client.get("/api/team", headers=headers).json()["invites"] == []
    # Preview reports it dead; accept is refused.
    assert client.get(f"/api/invite/{token}").json() == {
        "valid": False, "organizationName": None, "email": None, "reason": "revoked"
    }
    assert client.post(f"/api/invite/{token}/accept", json={"password": "password123"}).status_code == 400


def test_token_cannot_be_reused(owner):
    client, headers = owner
    client.post("/api/team/invites", headers=headers, json={"email": "once@alpha-gc.com"})
    token = _token_for("once@alpha-gc.com")
    assert client.post(f"/api/invite/{token}/accept", json={"password": "password123"}).status_code == 201
    # Second accept with the same token is refused (already used).
    assert client.post(f"/api/invite/{token}/accept", json={"password": "password123"}).status_code == 400


def test_expired_invite_is_refused(owner):
    client, headers = owner
    client.post("/api/team/invites", headers=headers, json={"email": "late@alpha-gc.com"})
    token = _token_for("late@alpha-gc.com")
    # Backdate the expiry to simulate an old invite.
    with SessionLocal() as db:
        row = db.query(OrganizationInvite).filter(OrganizationInvite.token == token).first()
        row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()
    assert client.get(f"/api/invite/{token}").json()["reason"] == "expired"
    assert client.post(f"/api/invite/{token}/accept", json={"password": "password123"}).status_code == 400


def test_unknown_token_preview_and_accept(owner):
    client, _ = owner
    assert client.get("/api/invite/not-a-real-token").json() == {
        "valid": False, "organizationName": None, "email": None, "reason": "unknown"
    }
    assert client.post("/api/invite/not-a-real-token/accept", json={"password": "password123"}).status_code == 400


def test_accept_requires_a_strong_password(owner):
    client, headers = owner
    client.post("/api/team/invites", headers=headers, json={"email": "weak@alpha-gc.com"})
    token = _token_for("weak@alpha-gc.com")
    # < 8 chars → schema rejects before any user is created.
    assert client.post(f"/api/invite/{token}/accept", json={"password": "short"}).status_code == 422


# --------------------------------------------------------------------------- #
# Cross-org isolation: invites are tenant data.
# --------------------------------------------------------------------------- #

def test_invites_are_org_isolated(client):
    headers_a = _register(client, "a@alpha-gc.com", "Alpha GC")
    headers_b = _register(client, "b@beta-gc.com", "Beta GC")

    invite_id = client.post(
        "/api/team/invites", headers=headers_a, json={"email": "hire@alpha-gc.com"}
    ).json()["id"]

    # B's team page never shows A's invite.
    team_b = client.get("/api/team", headers=headers_b).json()
    assert all(i["email"] != "hire@alpha-gc.com" for i in team_b["invites"])
    assert [m["email"] for m in team_b["members"]] == ["b@beta-gc.com"]

    # B cannot revoke A's invite (404, not 403), and it survives.
    assert client.delete(f"/api/team/invites/{invite_id}", headers=headers_b).status_code == 404
    assert any(
        i["id"] == invite_id for i in client.get("/api/team", headers=headers_a).json()["invites"]
    )


def test_team_endpoints_require_auth(client):
    assert client.get("/api/team").status_code == 401
    assert client.post("/api/team/invites", json={"email": "x@y.com"}).status_code == 401
