"""The core procurement flow: BOM approval gate, RFQ state machine, and
idempotent, duplicate-safe sending — all against mock providers."""
import pytest

from app.services.rfq import sender as rfq_sender
from app.services.rfq import state as rfq_state
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search


def test_unapproved_bom_blocks_rfq(project):
    client, headers, pid = project
    # Build a custom BOM but do NOT confirm it.
    r = client.post(
        "/api/documents/manual", headers=headers, json={"name": "Pipes", "projectId": pid}
    )
    bom_id = r.json()["id"]
    client.put(
        f"/api/documents/{bom_id}/line-items",
        headers=headers,
        json={"groups": [{"group": "Pipes", "count": 1, "tone": "blue",
                          "items": [{"n": "8-inch PVC pipe", "q": "100 LF"}]}]},
    )
    # Package BOM withholds unapproved items and reports them as pending.
    r = client.get(f"/api/projects/{pid}/packages/{bom_id}/bom", headers=headers)
    assert r.json()["count"] == 0
    assert r.json()["pendingReview"] == 1
    # RFQ generation is blocked.
    sids = run_supplier_search(client, headers, pid, bom_id)
    r = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/rfqs/generate",
        headers=headers,
        json={"supplier_ids": sids[:2]},
    )
    assert r.status_code == 409
    assert "confirm" in r.json()["detail"].lower()
    # After confirmation it works.
    client.post(f"/api/documents/{bom_id}/confirm", headers=headers)
    r = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/rfqs/generate",
        headers=headers,
        json={"supplier_ids": sids[:2]},
    )
    assert r.status_code == 201
    assert len(r.json()["lineItems"]) == 1


def test_rfq_body_names_city_of_installation(project):
    """Suppliers ask for the install location to quote the right specs, so the
    generated RFQ body states the project's city up front."""
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:2])
    # "Austin, TX" is the project fixture's `loc`.
    assert "installed in Austin, TX" in rfq["body"]


def test_rfq_body_omits_city_when_location_unknown():
    """When a project has no real location we fall back to the original wording
    rather than emailing suppliers a placeholder city."""
    from app.services.rfq.generator import generate_rfq_draft

    draft = generate_rfq_draft(
        {"name": "Untitled", "loc": "—"},
        "Water Utilities",
        [{"n": '12" DI Pipe', "q": "100 LF"}],
        [{"id": "s1", "name": "Acme", "email": "acme@example.com"}],
    )
    assert "installed in" not in draft.body
    assert draft.body.startswith("We are requesting a quote.")


def test_send_is_duplicate_safe(project):
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:3])

    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "Awaiting"
    assert all(rec["sendStatus"] == "sent" for rec in body["recipients"])

    # A second send must be refused — no recipient is ever emailed twice.
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 409

    # A sent RFQ can no longer be edited.
    r = client.put(
        f"/api/projects/{pid}/rfqs/{rfq['id']}",
        headers=headers,
        json={"subject": "x", "body": "y", "recipients": body["recipients"]},
    )
    assert r.status_code == 409


def test_partial_failure_and_retry_only_failed(project, monkeypatch):
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:3])
    fail_email = rfq["recipients"][1]["email"]

    mock = rfq_sender.MockSender()

    class Flaky:
        def send(self, to, subject, body, from_addr=""):
            if to == fail_email:
                raise RuntimeError("smtp boom")
            return mock.send(to, subject, body, from_addr=from_addr)

    monkeypatch.setattr(rfq_sender, "get_sender", lambda: Flaky())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "Send failed"
    failed = [rec for rec in body["recipients"] if rec["sendStatus"] == "failed"]
    assert [rec["email"] for rec in failed] == [fail_email]
    assert "smtp boom" in failed[0]["sendError"]
    ok_ids = {rec["email"]: rec["sentMessageId"] for rec in body["recipients"]
              if rec["sendStatus"] == "sent"}

    # Retry: only the failed recipient is attempted; delivered ones untouched.
    sent_to = []

    class Counting:
        def send(self, to, subject, body, from_addr=""):
            sent_to.append(to)
            return mock.send(to, subject, body, from_addr=from_addr)

    monkeypatch.setattr(rfq_sender, "get_sender", lambda: Counting())
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200
    assert sent_to == [fail_email]
    body = r.json()
    assert body["status"] == "Awaiting"
    for rec in body["recipients"]:
        if rec["email"] in ok_ids:
            assert rec["sentMessageId"] == ok_ids[rec["email"]]


def test_ingest_flips_rfq_to_quoted(project):
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:2])
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)

    r = client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    assert r.status_code == 202
    r = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers)
    data = r.json()
    assert data["status"] == "done"
    assert data["mocked"] is True
    assert data["ingested"] == 2

    r = client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers)
    assert r.json()["status"] == "Quoted"

    # Ingest is idempotent: a second run ingests nothing new.
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    r = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers)
    assert r.json()["ingested"] == 0


def test_state_machine_rejects_illegal_transitions():
    with pytest.raises(rfq_state.IllegalTransition):
        rfq_state.assert_transition("Quoted", "Draft")
    with pytest.raises(rfq_state.IllegalTransition):
        rfq_state.assert_transition("Draft", "Quoted")
    with pytest.raises(rfq_state.IllegalTransition):
        rfq_state.assert_transition("Awaiting", "Draft")
    # legal moves + idempotent same-state
    rfq_state.assert_transition("Draft", "Awaiting")
    rfq_state.assert_transition("Send failed", "Awaiting")
    rfq_state.assert_transition("Awaiting", "Quoted")
    rfq_state.assert_transition("Quoted", "Quoted")
