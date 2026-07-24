"""Quote comparison, awards (purchase decisions), and audit-trail coverage."""
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search


def _run_flow_to_quotes(client, headers, pid):
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:3])
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    return bom_id, rfq


def test_line_comparison_and_award_records_decision(project):
    client, headers, pid = project
    bom_id, _rfq = _run_flow_to_quotes(client, headers, pid)

    # Mock quotes are priced per line — the comparison grid is real.
    r = client.get(
        f"/api/projects/{pid}/packages/{bom_id}/line-comparison", headers=headers
    )
    assert r.status_code == 200
    lc = r.json()
    assert {l["name"] for l in lc["lines"]} == {"Fire hydrant", "8-inch gate valve"}
    assert {o["key"] for o in lc["options"]} >= {"mix", "single"}
    assert all(o["total"] > 0 for o in lc["options"])

    # Award (mix strategy, empty selection → cheapest fill).
    r = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/award",
        headers=headers,
        json={"selections": {}, "strategy": "mix"},
    )
    assert r.status_code == 200
    assert r.json()["total"] > 0

    # The decision is durably recorded with its decision maker.
    r = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers)
    decisions = r.json()
    assert len(decisions) == 1
    d = decisions[0]
    assert d["decidedByEmail"] == "pm@example.com"
    assert d["strategy"] == "mix"
    assert d["total"] > 0
    assert d["poCount"] >= 1
    assert d["suppliers"]

    # Awarding is deterministic/idempotent in effect: a repeat award writes a
    # second decision record (history) but the same winning selection.
    r = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/award",
        headers=headers,
        json={"selections": {}, "strategy": "mix"},
    )
    assert r.status_code == 200
    r = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers)
    assert len(r.json()) == 2
    assert r.json()[0]["suppliers"] == r.json()[1]["suppliers"]


def test_award_emails_suppliers_and_records_it(project):
    client, headers, pid = project
    bom_id, _rfq = _run_flow_to_quotes(client, headers, pid)

    r = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/award",
        headers=headers,
        json={"selections": {}, "strategy": "mix"},
    )
    assert r.status_code == 200
    assert "notified" in r.json()["message"]  # award message reports the notifications

    events = client.get("/api/audit", headers=headers).json()
    notified = [e for e in events if e["action"] == "package.award_notified"]
    assert notified, "expected a package.award_notified audit event"
    detail = notified[0]["detail"]
    assert detail["mock"] is True  # tests never hit real Gmail
    assert detail["awarded"]  # at least one awarded supplier was emailed


def test_audit_covers_the_whole_workflow(project):
    client, headers, pid = project
    bom_id, _rfq = _run_flow_to_quotes(client, headers, pid)
    client.post(
        f"/api/projects/{pid}/packages/{bom_id}/award",
        headers=headers,
        json={"selections": {}, "strategy": "mix"},
    )

    r = client.get("/api/audit", headers=headers)
    events = r.json()
    actions = {e["action"] for e in events}
    assert {
        "auth.registered",
        "project.created",
        "bom.created_manual",
        "bom.edited",
        "bom.confirmed",
        "supplier_search.started",
        "rfq.drafted",
        "rfq.sent",
        "quotes.ingest_started",
        "package.awarded",
    } <= actions

    # Every event names its actor.
    assert all(e["actorEmail"] == "pm@example.com" for e in events)

    # The send event records the delivery outcome (and that it was mocked).
    sent = next(e for e in events if e["action"] == "rfq.sent")
    assert sent["detail"]["delivered"] == 3
    assert sent["detail"]["mock"] is True

    # Project filter works.
    r = client.get(f"/api/audit?project_id={pid}", headers=headers)
    assert all(e["projectId"] == pid for e in r.json())


def test_audit_is_read_only(auth):
    """The audit trail is append-only: the API exposes no mutation routes."""
    client, headers = auth
    assert client.post("/api/audit", headers=headers).status_code == 405
    assert client.delete("/api/audit", headers=headers).status_code == 405
    assert client.put("/api/audit", headers=headers).status_code == 405
