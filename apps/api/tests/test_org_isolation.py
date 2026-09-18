"""Cross-organization isolation — the tenant boundary must hold on every route.

The app is auth-gated, but auth alone does not stop one logged-in tenant from
reading another tenant's data by id. These tests register two independent
organizations and assert that org B can neither see nor mutate anything owned by
org A, across every tenant-scoped route.

Two invariants are load-bearing and asserted explicitly:

1. A cross-org access returns **404, never 403 and never 200**. A 403 would
   confirm the id is real (it exists, you just can't have it), which leaks that
   a competitor is bidding the same job. 404 is indistinguishable from "no such
   id."
2. A cross-org mutation leaves the target **unchanged** — a failed delete/award
   must not partially apply.

The seeded demo data (demo RFQs, demo quotes, dashboard metric literals) is
global and identical for every tenant by design, so it is deliberately NOT
covered here — there is nothing tenant-specific to leak. See the per-route
comments in app/api/routes/ for which paths are global.
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_confirmed_bom, run_supplier_search


def _register(client: TestClient, email: str, company: str) -> dict:
    """Register a fresh user (→ a fresh organization) and return its headers."""
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "name": email.split("@")[0], "company": company},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


def _new_project(client: TestClient, headers: dict, name: str) -> str:
    r = client.post(
        "/api/projects",
        headers=headers,
        json={"name": name, "loc": "Austin, TX", "type": "Commercial"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def two_orgs(client):
    """(client, headers_a, headers_b) — two users in two distinct organizations."""
    headers_a = _register(client, "a@alpha-gc.com", "Alpha GC")
    headers_b = _register(client, "b@beta-gc.com", "Beta GC")
    return client, headers_a, headers_b


# --------------------------------------------------------------------------- #
# Registration: one org per signup, but the data model allows many per org.
# --------------------------------------------------------------------------- #

def test_register_creates_distinct_org_per_signup(two_orgs):
    """Two signups land in two different tenants — B's workspace is empty of A's."""
    client, headers_a, headers_b = two_orgs
    _new_project(client, headers_a, "Alpha Tower")

    # A sees exactly its own project; B sees none of A's.
    assert [p["name"] for p in client.get("/api/projects", headers=headers_a).json()] == ["Alpha Tower"]
    assert client.get("/api/projects", headers=headers_b).json() == []


def test_two_users_can_share_one_organization(client):
    """The invite path isn't built, but the model supports many users per org:
    two users created into the same org share its data."""
    from app.db import SessionLocal
    from app.repositories import organizations as organizations_repo
    from app.repositories import projects as projects_repo
    from app.repositories import users as users_repo

    with SessionLocal() as db:
        org = organizations_repo.create_organization(db, "Shared GC")
        u1 = users_repo.create_user(db, org.id, email="one@shared.com", password="password123", name="One")
        u2 = users_repo.create_user(db, org.id, email="two@shared.com", password="password123", name="Two")
        assert u1.organization_id == u2.organization_id == org.id

        projects_repo.create_project(db, org.id, name="Shared Job")
        names = [p["name"] for p in projects_repo.list_projects(db, org.id)]
        assert names == ["Shared Job"]  # visible to the org, hence to both users


# --------------------------------------------------------------------------- #
# Projects — read isolation.
# --------------------------------------------------------------------------- #

def test_project_list_is_isolated(two_orgs):
    client, headers_a, headers_b = two_orgs
    _new_project(client, headers_a, "Alpha Job")
    _new_project(client, headers_b, "Beta Job")

    a_names = {p["name"] for p in client.get("/api/projects", headers=headers_a).json()}
    b_names = {p["name"] for p in client.get("/api/projects", headers=headers_b).json()}
    assert a_names == {"Alpha Job"}
    assert b_names == {"Beta Job"}


def test_get_foreign_project_is_404(two_orgs):
    client, headers_a, headers_b = two_orgs
    pid = _new_project(client, headers_a, "Alpha Job")

    r = client.get(f"/api/projects/{pid}", headers=headers_b)
    assert r.status_code == 404, r.text
    # A can still read its own — proves the id is real and only B is blocked.
    assert client.get(f"/api/projects/{pid}", headers=headers_a).status_code == 200


def test_foreign_project_subresources_are_404(two_orgs):
    """Every nested read under a foreign project id 404s, not just the root."""
    client, headers_a, headers_b = two_orgs
    pid = _new_project(client, headers_a, "Alpha Job")

    for path in (
        f"/api/projects/{pid}/documents",
        f"/api/projects/{pid}/line-items",
        f"/api/projects/{pid}/suppliers",
        f"/api/projects/{pid}/quotes",
        f"/api/projects/{pid}/rfqs",
        f"/api/projects/{pid}/timeline",
        f"/api/projects/{pid}/purchase-decisions",
        f"/api/projects/{pid}/packages/hydrants/comparison",
    ):
        r = client.get(path, headers=headers_b)
        assert r.status_code == 404, f"{path} → {r.status_code} (expected 404)\n{r.text}"


# --------------------------------------------------------------------------- #
# Projects — mutation isolation (must 404 AND leave the target untouched).
# --------------------------------------------------------------------------- #

def test_delete_foreign_project_is_404_and_leaves_it_intact(two_orgs):
    client, headers_a, headers_b = two_orgs
    pid = _new_project(client, headers_a, "Alpha Job")

    assert client.delete(f"/api/projects/{pid}", headers=headers_b).status_code == 404
    # Still there for its real owner.
    assert client.get(f"/api/projects/{pid}", headers=headers_a).status_code == 200


def test_award_on_foreign_project_is_404(two_orgs):
    """A cross-org award is refused at the project gate, before any quote logic."""
    client, headers_a, headers_b = two_orgs
    pid = _new_project(client, headers_a, "Alpha Job")

    r = client.post(
        f"/api/projects/{pid}/packages/hydrants/award",
        headers=headers_b,
        json={"selections": {}, "strategy": "optimal"},
    )
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# Documents.
# --------------------------------------------------------------------------- #

def test_get_foreign_document_is_404(two_orgs):
    client, headers_a, headers_b = two_orgs
    pid = _new_project(client, headers_a, "Alpha Job")
    doc_id = make_confirmed_bom(client, headers_a, pid)

    assert client.get(f"/api/documents/{doc_id}", headers=headers_b).status_code == 404
    assert client.get(f"/api/documents/{doc_id}/file-url", headers=headers_b).status_code == 404
    # Real for its owner.
    assert client.get(f"/api/documents/{doc_id}", headers=headers_a).status_code == 200


def test_mutate_foreign_document_is_404_and_unchanged(two_orgs):
    client, headers_a, headers_b = two_orgs
    pid = _new_project(client, headers_a, "Alpha Job")
    doc_id = make_confirmed_bom(client, headers_a, pid)
    before = client.get(f"/api/documents/{doc_id}", headers=headers_a).json()

    # B tries to overwrite A's line items. The body must be VALID (a schema-
    # invalid body would 422 before the route runs, masking whether the
    # ownership check exists at all) so execution actually reaches the org gate.
    r = client.put(
        f"/api/documents/{doc_id}/line-items",
        headers=headers_b,
        json={"groups": [{"group": "Injected", "count": 1, "tone": "danger",
                          "items": [{"n": "Tamper", "q": "1 EA"}]}]},
    )
    assert r.status_code == 404, r.text
    # B tries to delete A's document.
    assert client.delete(f"/api/documents/{doc_id}", headers=headers_b).status_code == 404

    # A's document is byte-for-byte what it was.
    after = client.get(f"/api/documents/{doc_id}", headers=headers_a).json()
    assert after == before


# --------------------------------------------------------------------------- #
# Quotes — a real ingested quote (not the global demo quotes) must not leak.
# --------------------------------------------------------------------------- #

def test_foreign_quote_is_404(two_orgs):
    client, headers_a, headers_b = two_orgs
    pid = _new_project(client, headers_a, "Alpha Job")

    from app.db import SessionLocal
    from app.repositories import projects as projects_repo
    from app.repositories import quotes as quotes_repo

    with SessionLocal() as db:
        # Resolve A's org id from its project, then plant a real quote in it.
        org_a = None
        # projects.get_row exposes the ORM row incl. organization_id.
        row = projects_repo.get_row(db, _org_of(client, headers_a), pid)
        org_a = row.organization_id
        quote = quotes_repo.create_quote(
            db, org_a, project_id=pid, package="hydrants", package_label="Hydrants",
            supplier_name="Acme Pipe", total=12345.0, status="received", source="ingest",
        )
        quote_id = quote["id"]

        # Repo-level: B's org cannot read A's quote.
        assert quotes_repo.get_quote(db, _org_of(client, headers_b), quote_id) is None

    # API-level: B GETs the real quote id → 404 (it is not a global demo quote).
    assert client.get(f"/api/quotes/{quote_id}", headers=headers_b).status_code == 404
    # A can read it.
    assert client.get(f"/api/quotes/{quote_id}", headers=headers_a).status_code == 200


# --------------------------------------------------------------------------- #
# Background jobs — a job carries project ids + search params; retry re-runs work.
# --------------------------------------------------------------------------- #

def test_jobs_are_isolated(two_orgs):
    client, headers_a, headers_b = two_orgs
    pid = _new_project(client, headers_a, "Alpha Job")
    # A custom BOM is searched using its own doc id as the package key.
    bom_id = make_confirmed_bom(client, headers_a, pid, name="Hydrants Package")
    # Mock supplier search creates a completed search job owned by org A.
    run_supplier_search(client, headers_a, pid, bom_id)

    a_jobs = client.get("/api/jobs", headers=headers_a).json()
    b_jobs = client.get("/api/jobs", headers=headers_b).json()
    a_ids = {j["id"] for j in a_jobs}
    assert a_ids, "org A should have at least one job"
    assert {j["id"] for j in b_jobs}.isdisjoint(a_ids)

    # B cannot retry A's job.
    stolen = next(iter(a_ids))
    assert client.post(f"/api/jobs/{stolen}/retry", headers=headers_b).status_code == 404


# --------------------------------------------------------------------------- #
# Audit trail + dashboard activity — both are real customer data, org-scoped.
# --------------------------------------------------------------------------- #

def test_audit_trail_is_isolated(two_orgs):
    client, headers_a, headers_b = two_orgs
    _new_project(client, headers_a, "Alpha Job")  # logs project.created for A

    a_events = client.get("/api/audit", headers=headers_a).json()
    b_events = client.get("/api/audit", headers=headers_b).json()
    assert any(e["action"] == "project.created" for e in a_events)
    # None of A's project.created events appear in B's trail.
    assert not any(e["action"] == "project.created" for e in b_events)


def test_dashboard_activity_is_isolated(two_orgs):
    """Dashboard metric numbers are global seed literals (shared by design); the
    activity feed is real per-tenant data and must not cross."""
    client, headers_a, headers_b = two_orgs
    _new_project(client, headers_a, "Alpha Distinctive Job")

    a_activity = client.get("/api/dashboard", headers=headers_a).json().get("activity", [])
    b_activity = client.get("/api/dashboard", headers=headers_b).json().get("activity", [])
    # list_recent prefixes each item's meta with the project name, so match on
    # substring: A's feed carries the job, B's feed never mentions it.
    assert any("Alpha Distinctive Job" in (item.get("meta") or "") for item in a_activity)
    assert all("Alpha Distinctive Job" not in (item.get("meta") or "") for item in b_activity)


def test_timeline_done_on_foreign_event_is_404(two_orgs):
    """Timeline event ids are sequential ints, so they're trivially guessable —
    a done-toggle on an id the caller's org doesn't own must 404."""
    client, headers_a, headers_b = two_orgs
    r = client.post("/api/timeline/events/1/done", headers=headers_b, json={"done": True})
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# The load-bearing invariant: cross-org is 404, never 403, never 200.
# --------------------------------------------------------------------------- #

def test_cross_org_access_is_404_never_403(two_orgs):
    client, headers_a, headers_b = two_orgs
    pid = _new_project(client, headers_a, "Alpha Job")
    doc_id = make_confirmed_bom(client, headers_a, pid)

    probes = [
        ("GET", f"/api/projects/{pid}"),
        ("DELETE", f"/api/projects/{pid}"),
        ("GET", f"/api/projects/{pid}/documents"),
        ("GET", f"/api/documents/{doc_id}"),
        ("DELETE", f"/api/documents/{doc_id}"),
    ]
    for method, path in probes:
        r = client.request(method, path, headers=headers_b)
        assert r.status_code == 404, f"{method} {path} → {r.status_code} (want 404)"
        assert r.status_code != 403, f"{method} {path} leaked existence via 403"


# --------------------------------------------------------------------------- #
# Helper: resolve a user's org id (no API field exposes it, so read via /me + db).
# --------------------------------------------------------------------------- #

def _org_of(client: TestClient, headers: dict) -> str:
    """The organization id behind a set of auth headers."""
    from app.db import SessionLocal
    from app.repositories import users as users_repo

    email = client.get("/api/auth/me", headers=headers).json()["email"]
    with SessionLocal() as db:
        return users_repo.get_by_email(db, email).organization_id
