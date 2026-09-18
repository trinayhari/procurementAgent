"""Round-3 reliability regressions: dashboard KPIs, project overview cards and
package progress computed from real rows (no seeded literals, no demo-only
path), and real per-package budgets replacing the hard-coded sample."""
from app.db import SessionLocal
from app.services import metrics as metrics_service
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search


def _metrics(client, headers) -> dict:
    r = client.get("/api/dashboard", headers=headers)
    assert r.status_code == 200, r.text
    return {m["label"]: m for m in r.json()["metrics"]}


def _cards(client, headers, pid) -> dict:
    r = client.get(f"/api/projects/{pid}", headers=headers)
    assert r.status_code == 200, r.text
    return {c["label"]: c for c in r.json()["overviewCards"]}


def _packages(client, headers, pid) -> dict:
    return {p["name"]: p for p in client.get(f"/api/projects/{pid}", headers=headers).json()["packages"]}


def _flow_to_quotes(client, headers, pid):
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:3])
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    return bom_id, rfq


# ------------------------------------------------------------- dashboard KPIs
def test_dashboard_kpis_follow_the_project_through_the_flow(project):
    """Each tile is derived from the org's rows at every step: nothing is a
    literal, the savings tile appears only once an award exists."""
    client, headers, pid = project
    m = _metrics(client, headers)
    assert m["Active projects"]["value"] == "0"
    assert m["Active projects"]["sub"] == "of 1 project with documents"
    assert m["RFQs out"]["value"] == "0"
    assert m["Quotes received"]["value"] == "0"
    assert m["Spend committed"]["value"] == "$0"
    assert "Savings" not in m
    assert all(x["delta"] == "" for x in m.values())  # no invented trends

    # A (custom BOM) document makes the project active; an Awaiting RFQ is "out".
    bom_id, rfq = _flow_to_quotes(client, headers, pid)
    m = _metrics(client, headers)
    assert m["Active projects"]["value"] == "1"
    assert m["RFQs out"]["value"] == "1"
    assert m["Quotes received"]["value"] == "0"

    # Quotes back → the RFQ is Quoted (no longer out) and quotes count up.
    r = client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    assert r.status_code == 202, r.text
    quotes = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert len(quotes) >= 2
    m = _metrics(client, headers)
    assert m["Quotes received"]["value"] == str(len(quotes))
    assert m["RFQs out"]["value"] == "0"
    assert "Savings" not in m

    # Award → spend committed = the decision total; savings = highest quote − awarded.
    r = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/award",
        headers=headers,
        json={"selections": {}, "strategy": "mix"},
    )
    assert r.status_code == 200, r.text
    awarded_total = r.json()["total"]
    with SessionLocal() as db:
        from app.models.quote import Quote
        from sqlalchemy import select
        highest = max(
            q.total for q in db.scalars(select(Quote).where(Quote.project_id == pid)).all()
            if q.total is not None
        )
    m = _metrics(client, headers)
    assert m["Spend committed"]["value"] == metrics_service._money(awarded_total)
    assert m["Spend committed"]["sub"] == "1 package awarded"
    assert m["Savings"]["value"] == metrics_service._money(highest - awarded_total)
    assert m["Savings"]["ai"] is True


def test_spend_counts_only_the_latest_award_per_package(project):
    client, headers, pid = project
    bom_id, _rfq = _flow_to_quotes(client, headers, pid)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    first = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/award",
        headers=headers, json={"selections": {}, "strategy": "mix"},
    ).json()["total"]
    again = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/award",
        headers=headers, json={"selections": {}, "strategy": "single", "supersede": True},
    )
    assert again.status_code == 200, again.text
    with SessionLocal() as db:
        awarded, spend, _savings = metrics_service.award_figures(db, "org-unused-check", pid)
    assert awarded == 0  # wrong org sees nothing
    with SessionLocal() as db:
        from app.models.user import User
        org_id = db.scalars(__import__("sqlalchemy").select(User)).first().organization_id
        awarded, spend, _savings = metrics_service.award_figures(db, org_id, pid)
    assert awarded == 1
    assert spend == again.json()["total"]  # superseded award is no longer committed
    assert spend != first + again.json()["total"]


def test_kpis_are_tenant_scoped(project):
    """Another organization's documents, RFQs and quotes never count."""
    client, headers, pid = project
    _flow_to_quotes(client, headers, pid)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    r = client.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "password123", "name": "Other"},
    )
    other = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    m = _metrics(client, other)
    assert m["Active projects"]["value"] == "0"
    assert m["Active projects"]["sub"] == "of 0 projects with documents"
    assert m["RFQs out"]["value"] == "0"
    assert m["Quotes received"]["value"] == "0"


def test_money_format():
    assert metrics_service._money(0) == "$0"
    assert metrics_service._money(4250) == "$4,250"
    assert metrics_service._money(35_300) == "$35.3K"
    assert metrics_service._money(120_000) == "$120K"
    assert metrics_service._money(1_840_000) == "$1.84M"
    assert metrics_service._money(-1_500) == "-$1,500"


# ------------------------------------------------- project overview + packages
def test_overview_cards_and_package_progress_are_computed_per_project(project):
    client, headers, pid = project
    cards = _cards(client, headers, pid)
    assert [c["value"] for c in cards.values()] == ["0", "0", "0", "0"]
    assert "Savings identified" not in cards
    assert _packages(client, headers, pid) == {}

    # Custom BOM confirmed → a document, and the package shows "Items identified".
    bom_id = make_confirmed_bom(client, headers, pid, name="Hydrants Package")
    cards = _cards(client, headers, pid)
    assert cards["Documents"]["value"] == "1"
    assert cards["Documents"]["sub"] == "1 analyzed · 1 confirmed"
    pk = _packages(client, headers, pid)["Hydrants Package"]
    assert (pk["pct"], pk["stage"]) == (10, "Items identified")

    # Search + RFQ draft + send.
    sids = run_supplier_search(client, headers, pid, bom_id)
    cards = _cards(client, headers, pid)
    assert cards["Suppliers found"]["value"] == str(len(sids))
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:3])
    pk = _packages(client, headers, pid)["Hydrants Package"]
    assert (pk["pct"], pk["stage"]) == (25, "RFQ drafted")
    cards = _cards(client, headers, pid)
    assert cards["RFQs sent"]["value"] == "0" and "1 draft" in cards["RFQs sent"]["sub"]
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    pk = _packages(client, headers, pid)["Hydrants Package"]
    assert (pk["pct"], pk["stage"], pk["tone"]) == (50, "RFQ sent", "blue")
    assert _cards(client, headers, pid)["RFQs sent"]["value"] == "1"

    # Quotes in.
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    quotes = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    cards = _cards(client, headers, pid)
    assert cards["Quotes received"]["value"] == str(len(quotes))
    assert cards["Quotes received"]["sub"] == "1 package"
    assert cards["Suppliers found"]["sub"].endswith("quoted")
    assert cards["RFQs sent"]["sub"].startswith("1 quoted")
    pk = _packages(client, headers, pid)["Hydrants Package"]
    assert (pk["pct"], pk["stage"]) == (75, "Quotes in")

    # Awarded → 100% and the savings card appears.
    r = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/award",
        headers=headers, json={"selections": {}, "strategy": "mix"},
    )
    assert r.status_code == 200
    pk = _packages(client, headers, pid)["Hydrants Package"]
    assert (pk["pct"], pk["stage"], pk["tone"]) == (100, "Awarded", "success")
    cards = _cards(client, headers, pid)
    assert cards["Savings identified"]["ai"] is True
    assert "1 package awarded" in cards["Savings identified"]["sub"]


def test_overview_is_per_project_not_shared(project):
    """Two projects in one org show their OWN figures (the seeded cards were
    identical on every project)."""
    client, headers, pid = project
    make_confirmed_bom(client, headers, pid)
    r = client.post("/api/projects", headers=headers, json={"name": "Second", "loc": "Reno, NV"})
    pid2 = r.json()["id"]
    assert _cards(client, headers, pid)["Documents"]["value"] == "1"
    assert _cards(client, headers, pid2)["Documents"]["value"] == "0"
    assert _packages(client, headers, pid2) == {}


def test_preset_category_package_progress_from_extracted_items(project):
    """A preset discipline (water) with extracted, confirmed items is a package
    at 'Items identified' even before any RFQ exists."""
    client, headers, pid = project
    from app.repositories import documents as documents_repo
    with SessionLocal() as db:
        from app.models.user import User
        from sqlalchemy import select
        org_id = db.scalars(select(User)).first().organization_id
        doc = documents_repo.add(
            db, org_id=org_id, project_id=pid, name="Utility plan", doc_type="Utility Plans",
            date="Sep 1", status="Analyzed", status_tone="success", pages=1, plan_type="site_plan",
        )
        documents_repo.set_line_items(
            db, org_id, doc.id,
            [{"group": "Water Materials", "count": 1, "tone": "blue", "items": [{"n": '12" DI Pipe', "q": "100 LF"}]}],
        )
    pk = _packages(client, headers, pid)
    assert pk["Water Utilities"]["stage"] == "Items identified"
    assert _cards(client, headers, pid)["Documents"]["sub"] == "1 analyzed · 0 confirmed"


# ------------------------------------------------------------------ budgets
def test_budget_is_optional_real_and_per_package(project):
    """No sample budget: a fresh package has none, the comparison carries null
    until the buyer sets one, and clearing it hides the line again."""
    client, headers, pid = project
    bom_id, _rfq = _flow_to_quotes(client, headers, pid)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)

    r = client.get(f"/api/projects/{pid}/packages/{bom_id}/line-comparison", headers=headers)
    assert r.status_code == 200
    assert r.json()["budget"] is None
    r = client.get(f"/api/projects/{pid}/packages/{bom_id}/budget", headers=headers)
    assert r.json() == {"package": bom_id, "budget": None}

    r = client.put(f"/api/projects/{pid}/packages/{bom_id}/budget", headers=headers, json={"budget": 42_000})
    assert r.status_code == 200, r.text
    assert r.json() == {"package": bom_id, "budget": 42_000.0}
    r = client.get(f"/api/projects/{pid}/packages/{bom_id}/line-comparison", headers=headers)
    assert r.json()["budget"] == 42_000.0
    # Idempotent update, not a second row.
    r = client.put(f"/api/projects/{pid}/packages/{bom_id}/budget", headers=headers, json={"budget": 50_000})
    assert r.json()["budget"] == 50_000.0
    with SessionLocal() as db:
        from app.models.package_budget import PackageBudget
        from sqlalchemy import func, select
        assert db.scalar(select(func.count()).select_from(PackageBudget)) == 1

    # Another package on the same project is unaffected; a preset label resolves to its key.
    r = client.get(f"/api/projects/{pid}/packages/Water%20Utilities/budget", headers=headers)
    assert r.json() == {"package": "water", "budget": None}

    # Validation: a budget must be a positive amount.
    r = client.put(f"/api/projects/{pid}/packages/{bom_id}/budget", headers=headers, json={"budget": -5})
    assert r.status_code == 422
    r = client.put(f"/api/projects/{pid}/packages/{bom_id}/budget", headers=headers, json={"budget": 0})
    assert r.status_code == 422

    # Clear it.
    r = client.put(f"/api/projects/{pid}/packages/{bom_id}/budget", headers=headers, json={"budget": None})
    assert r.status_code == 200
    assert r.json()["budget"] is None
    assert client.get(f"/api/projects/{pid}/packages/{bom_id}/line-comparison", headers=headers).json()["budget"] is None
    # …and the audit trail has both events.
    audit = client.get("/api/audit", headers=headers).json()
    actions = [a["action"] for a in (audit if isinstance(audit, list) else audit.get("events", []))]
    assert actions.count("package.budget_set") >= 2


def test_budget_is_tenant_scoped(project):
    client, headers, pid = project
    r = client.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "password123", "name": "Other"},
    )
    other = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    assert client.put(f"/api/projects/{pid}/packages/water/budget", headers=other, json={"budget": 10}).status_code == 404
    assert client.get(f"/api/projects/{pid}/packages/water/budget", headers=other).status_code == 404


def test_no_sample_budget_remains():
    from app.services.quotes import sample_data
    assert not hasattr(sample_data, "budget_for")
    assert all("budget" not in spec for spec in sample_data.SAMPLE_PACKAGES.values())
