"""Subcontractor trade scopes: CRUD, search, and the bid-request RFQ flow.

A trade scope is a file-less Document whose id doubles as a package key, so it
flows through the same search → select → generate → send pipeline as custom
BOMs — but generates a scope-of-work bid request (kind="subcontractor") with no
BOM line items and no approval gate.
"""
from tests.conftest import make_confirmed_bom, run_supplier_search


def make_trade(client, headers, project_id, name="Concrete flatwork", scope=""):
    r = client.post(
        f"/api/projects/{project_id}/trades",
        headers=headers,
        json={"name": name, "scope": scope},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------- CRUD
def test_trade_scope_create_list_update(project):
    client, headers, pid = project
    trade = make_trade(client, headers, pid, scope="Pour 12,400 SF of sidewalk.")
    assert trade["name"] == "Concrete flatwork"
    assert trade["scope"] == "Pour 12,400 SF of sidewalk."

    r = client.get(f"/api/projects/{pid}/trades", headers=headers)
    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == [trade["id"]]

    r = client.put(
        f"/api/projects/{pid}/trades/{trade['id']}",
        headers=headers,
        json={"scope": "Updated scope."},
    )
    assert r.status_code == 200
    assert r.json()["scope"] == "Updated scope."


def test_trade_scope_is_a_deletable_document_not_an_additional_doc(project):
    client, headers, pid = project
    trade = make_trade(client, headers, pid)

    # It exists as a document with the trade_scope plan type (frontend groups
    # them into their own card off planType).
    r = client.get(f"/api/projects/{pid}/documents", headers=headers)
    docs = {d["id"]: d for d in r.json()}
    assert docs[trade["id"]]["planType"] == "trade_scope"

    # Standard document delete works (no file to unlink).
    r = client.delete(f"/api/documents/{trade['id']}", headers=headers)
    assert r.status_code == 204
    r = client.get(f"/api/projects/{pid}/trades", headers=headers)
    assert r.json() == []


def test_blank_trade_name_defaults_to_trade(project):
    client, headers, pid = project
    trade = make_trade(client, headers, pid, name="   ")
    assert trade["name"] == "Trade"


def test_update_scope_on_non_trade_document_is_404(project):
    """The /trades update route only writes scopes onto trade-scope documents —
    a custom BOM (also file-less) is not silently editable through it."""
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    r = client.put(
        f"/api/projects/{pid}/trades/{bom_id}",
        headers=headers,
        json={"scope": "should not land"},
    )
    assert r.status_code == 404


# ------------------------------------------------------------------ search
def test_search_on_trade_id_returns_mock_contractors(project):
    client, headers, pid = project
    trade = make_trade(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, trade["id"])
    assert sids  # the ad-hoc mock supplies results labeled by the trade name

    r = client.get(
        f"/api/projects/{pid}/suppliers/found?package={trade['id']}", headers=headers
    )
    sup = r.json()["tiers"][0]["suppliers"][0]
    assert sup["materialCategories"] == ["Concrete flatwork"]


def test_search_rejects_unknown_package(project):
    client, headers, pid = project
    r = client.post(
        f"/api/projects/{pid}/packages/not-a-package/search-suppliers",
        headers=headers,
        json={"radius_mi": 75},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------- generate
def test_generate_without_scope_is_rejected(project):
    client, headers, pid = project
    trade = make_trade(client, headers, pid, scope="")
    sids = run_supplier_search(client, headers, pid, trade["id"])
    r = client.post(
        f"/api/projects/{pid}/packages/{trade['id']}/rfqs/generate",
        headers=headers,
        json={"supplier_ids": sids[:2]},
    )
    assert r.status_code == 400
    assert "scope of work" in r.json()["detail"]


def test_generate_bid_request_from_scope(project):
    client, headers, pid = project
    trade = make_trade(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, trade["id"])
    scope = "Furnish and install 12,400 SF of 5-inch sidewalk per C-401."
    r = client.post(
        f"/api/projects/{pid}/packages/{trade['id']}/rfqs/generate",
        headers=headers,
        json={"supplier_ids": sids[:2], "scope": scope},
    )
    assert r.status_code == 201, r.text
    rfq = r.json()

    # A subcontractor bid request: no line items, no approval gate, the scope
    # verbatim in the body, and a bid-flavored subject.
    assert rfq["kind"] == "subcontractor"
    assert rfq["lineItems"] == []
    assert scope in rfq["body"]
    assert rfq["subject"].startswith("Bid Request:")
    assert "Concrete flatwork" in rfq["subject"]
    assert rfq["recipients"]

    # The scope passed at generate time is persisted back onto the trade chip.
    r = client.get(f"/api/projects/{pid}/trades", headers=headers)
    assert r.json()[0]["scope"] == scope


def test_generate_uses_stored_scope_when_payload_has_none(project):
    client, headers, pid = project
    trade = make_trade(client, headers, pid, scope="Stored scope text.")
    sids = run_supplier_search(client, headers, pid, trade["id"])
    r = client.post(
        f"/api/projects/{pid}/packages/{trade['id']}/rfqs/generate",
        headers=headers,
        json={"supplier_ids": sids[:2]},
    )
    assert r.status_code == 201, r.text
    assert "Stored scope text." in r.json()["body"]


# -------------------------------------------------------------------- send
def test_send_bid_request_via_mock_sender(project):
    client, headers, pid = project
    trade = make_trade(client, headers, pid, scope="Scope.")
    sids = run_supplier_search(client, headers, pid, trade["id"])
    r = client.post(
        f"/api/projects/{pid}/packages/{trade['id']}/rfqs/generate",
        headers=headers,
        json={"supplier_ids": sids[:2]},
    )
    rfq = r.json()
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    sent = r.json()
    assert sent["status"] == "Awaiting"
    assert sent["kind"] == "subcontractor"
    assert all(rec["sendStatus"] == "sent" for rec in sent["recipients"])


# ------------------------------------------------------------ unit: drafting
def test_trade_keywords_target_installers_not_suppliers():
    from app.services.sourcing import packages

    assert packages.trade_keywords("Concrete flatwork") == [
        "Concrete flatwork contractor",
        "Concrete flatwork subcontractor",
        "Concrete flatwork company",
    ]
    # A trade the user already wrote as "contractor"/"subcontractor" isn't
    # double-suffixed ("Drywall Contractor contractor").
    assert packages.trade_keywords("Drywall Contractor") == [
        "Drywall Contractor",
        "Drywall Contractor company",
    ]
    assert packages.trade_keywords("Framing  Subcontractor") == [
        "Framing Subcontractor",
        "Framing Subcontractor company",
    ]
    assert packages.trade_keywords("   ") == []
    assert "not a" in packages.trade_verify_hint("Concrete flatwork")


def test_sub_draft_survives_missing_project_details():
    """Like the materials draft, the bid request drops clauses it has no data
    for — no buyer, project name, or location still reads grammatically."""
    from app.services.rfq import generator

    draft = generator.generate_sub_rfq_draft(
        {},  # no project name, no loc
        "Concrete Flatwork",
        "  Pour 12,400 SF of sidewalk.  ",
        [
            {"id": "s1", "name": "A Corp", "email": "a@x.com"},
            {"id": "s2", "name": "No Email Inc"},  # dropped: no email
        ],
        buyer=None,
    )
    assert draft.subject == "Bid Request: Concrete Flatwork — Project"
    assert draft.body.startswith(
        "We are seeking bids from qualified concrete flatwork subcontractors."
    )
    assert "Scope of work:\nPour 12,400 SF of sidewalk." in draft.body
    assert draft.line_items == []
    assert [r["email"] for r in draft.recipients] == ["a@x.com"]


# ---------------------------------------------------------- org isolation
def test_trade_scope_is_org_scoped(project):
    client, headers, pid = project
    trade = make_trade(client, headers, pid)

    # A second organization can't see or use the first org's trade scope.
    r = client.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "password123", "name": "Other"},
    )
    other = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    r = client.post(
        "/api/projects",
        headers=other,
        json={"name": "Other Project", "loc": "Denver, CO", "type": "Commercial"},
    )
    other_pid = r.json()["id"]

    r = client.get(f"/api/projects/{other_pid}/trades", headers=other)
    assert r.json() == []
    # Using the foreign trade id as a package key is an unknown package there.
    r = client.post(
        f"/api/projects/{other_pid}/packages/{trade['id']}/search-suppliers",
        headers=other,
        json={"radius_mi": 75},
    )
    assert r.status_code == 400
