"""Approval links: preview, one-click execute (once), 410 afterwards and on
expiry, PO numbers per org, cross-org isolation, and the in-process service
the Slack button uses."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
import pytest

from app.db import SessionLocal
from app.models.approval_token import ApprovalToken
from app.services import approvals as approvals_service
from app.services import notify
from app.services.notify import kinds
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search


def _register(client, email, company):
    r = client.post("/api/auth/register", json={"email": email, "password": "password123",
                                                 "name": email.split("@")[0], "company": company})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


def _project(client, headers, name="Test Project"):
    r = client.post("/api/projects", headers=headers, json={"name": name, "loc": "Austin, TX", "type": "Commercial"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ready_package(client, headers, pid, n=3, name="Hydrants Package"):
    """Run the flow to quotes; the mock ingest answers for everyone, so the
    readiness check mints the approval link. Returns (bom_id, token)."""
    bom_id = make_confirmed_bom(client, headers, pid, name=name)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:n])
    assert client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers).status_code == 200
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
    with SessionLocal() as db:
        row = db.query(ApprovalToken).filter(
            ApprovalToken.project_id == pid, ApprovalToken.package == bom_id
        ).order_by(ApprovalToken.created_at.desc()).first()
        assert row is not None, "readiness should have minted an approval token"
        return bom_id, row.token


def _expire(token):
    with SessionLocal() as db:
        row = db.query(ApprovalToken).filter(ApprovalToken.token == token).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()


class _Memo:
    name = "memo"

    def __init__(self):
        self.seen = []

    def notify(self, db, notice):
        self.seen.append(notice)


@pytest.fixture()
def memo():
    m = _Memo()
    notify.register(m)
    yield m
    notify._NOTIFIERS[:] = [n for n in notify._NOTIFIERS if n.name != "memo"]


# ------------------------------------------------------------------ preview

def test_preview_shows_the_card_without_auth(project):
    client, headers, pid = project
    bom_id, token = _ready_package(client, headers, pid)
    r = client.get(f"/api/approvals/{token}")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "pending"
    assert (p["projectId"], p["projectName"], p["package"], p["packageLabel"]) == (pid, "Test Project", bom_id, "Hydrants Package")
    assert p["suppliers"] and all(s["total"] == round(s["subtotal"] + s["freight"], 2) for s in p["suppliers"])
    assert p["total"] == round(sum(s["total"] for s in p["suppliers"]), 2)
    assert p["material"] > 0 and p["freight"] >= 0 and p["savings"] >= 0
    assert p["quotesReceived"] == 3 and p["recipientsTotal"] == 3
    assert p["expiresAt"] and p["decidedAt"] is None and p["alreadyAwarded"] is False


def test_unknown_token_is_404_and_rate_limited(client):
    assert client.get("/api/approvals/not-a-token").status_code == 404
    assert client.post("/api/approvals/not-a-token").status_code == 404
    for _ in range(40):
        r = client.get("/api/approvals/not-a-token")
    assert r.status_code == 429


# ------------------------------------------------------------------ execute

def test_execute_awards_once_then_410(project, memo):
    client, headers, pid = project
    bom_id, token = _ready_package(client, headers, pid)
    r = client.post(f"/api/approvals/{token}", json={"decided_by_email": "pm@example.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "awarded" and body["poCount"] >= 1
    assert body["projectId"] == pid and body["packageLabel"] == "Hydrants Package"
    assert body["decidedByEmail"] == "pm@example.com"
    assert [p["po"] for p in body["poNumbers"]] == [f"PO-1-{n:04d}" for n in range(1, body["poCount"] + 1)]
    assert {p["supplierName"] for p in body["poNumbers"]} == set(body["suppliers"])

    # The link is spent: a second click cannot issue POs again.
    assert client.post(f"/api/approvals/{token}").status_code == 410
    p = client.get(f"/api/approvals/{token}").json()
    assert p["status"] == "used" and p["decidedByEmail"] == "pm@example.com" and p["decidedAt"]

    # Same record as a dashboard award: decision, audit, activity, notices.
    (d,) = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json()
    assert d["decidedByEmail"] == "pm@example.com"  # a known member acts as themselves
    assert d["poNumbers"] == body["poNumbers"]
    audit = client.get("/api/audit", headers=headers).json()
    awarded = next(a for a in audit if a["action"] == "package.awarded")
    assert awarded["actorEmail"] == "pm@example.com"
    assert awarded["detail"]["poNumbers"] == [p["po"] for p in body["poNumbers"]]
    kinds_seen = [n.kind for n in memo.seen]
    assert kinds.AWARD_APPROVED in kinds_seen and kinds.PO_ISSUED in kinds_seen
    po_notice = next(n for n in memo.seen if n.kind == kinds.PO_ISSUED)
    assert po_notice.project_id == pid
    assert len(po_notice.lines) == body["poCount"]
    assert all(line.startswith("PO-1-") and " issued to " in line and "$" in line for line in po_notice.lines)


def test_execute_without_a_body_records_the_link_as_actor(project):
    client, headers, pid = project
    bom_id, token = _ready_package(client, headers, pid)
    r = client.post(f"/api/approvals/{token}")
    assert r.status_code == 200, r.text
    assert r.json()["decidedByEmail"] is None
    (d,) = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json()
    assert d["decidedByEmail"] == "approval-link"
    assert d["decidedBy"].startswith("approval-link:")


def test_expired_token_is_410(project):
    client, headers, pid = project
    bom_id, token = _ready_package(client, headers, pid)
    _expire(token)
    assert client.get(f"/api/approvals/{token}").json()["status"] == "expired"
    r = client.post(f"/api/approvals/{token}")
    assert r.status_code == 410 and "expired" in r.json()["detail"]
    assert client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json() == []


def test_link_after_a_dashboard_award_does_not_re_award(project):
    client, headers, pid = project
    bom_id, token = _ready_package(client, headers, pid)
    assert client.post(f"/api/projects/{pid}/packages/{bom_id}/award", headers=headers,
                       json={"selections": {}}).status_code == 200
    assert client.get(f"/api/approvals/{token}").json()["alreadyAwarded"] is True
    r = client.post(f"/api/approvals/{token}")
    assert r.status_code == 409 and "already awarded" in r.json()["detail"]
    # Still pending (not consumed) and exactly one decision on record.
    assert client.get(f"/api/approvals/{token}").json()["status"] == "pending"
    assert len(client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json()) == 1


def test_service_execute_is_callable_in_process(project):
    """The Slack interaction handler calls the service directly."""
    client, headers, pid = project
    bom_id, token = _ready_package(client, headers, pid)
    with SessionLocal() as db:
        result = approvals_service.execute(db, token, decided_by_email="Slack.User@example.com")
        assert result["status"] == "awarded" and result["poNumbers"]
        with pytest.raises(HTTPException) as exc:
            approvals_service.execute(db, token)
        assert exc.value.status_code == 410


# --------------------------------------------------------------- PO numbers

def test_po_numbers_increment_per_org_and_use_the_org_seq(client):
    ha = _register(client, "a@alpha-gc.com", "Alpha GC")
    hb = _register(client, "b@beta-gc.com", "Beta GC")
    pa = _project(client, ha, "Alpha Job")
    pb = _project(client, hb, "Beta Job")

    bom_a1, _ = _ready_package(client, ha, pa, n=2, name="Hydrants Package")
    r = client.post(f"/api/projects/{pa}/packages/{bom_a1}/award", headers=ha, json={"selections": {}})
    assert r.status_code == 200, r.text
    first = [p["po"] for p in r.json()["poNumbers"]]
    assert first and all(po.startswith("PO-1-") for po in first)

    bom_a2, _ = _ready_package(client, ha, pa, n=2, name="Valves Package")
    r = client.post(f"/api/projects/{pa}/packages/{bom_a2}/award", headers=ha, json={"selections": {}})
    second = [p["po"] for p in r.json()["poNumbers"]]
    nums = [int(po.rsplit("-", 1)[1]) for po in first + second]
    assert nums == list(range(1, len(nums) + 1))  # one org counter, never reused

    # Org B has its own sequence starting at 1 with its own org seq.
    bom_b, _ = _ready_package(client, hb, pb, n=2)
    r = client.post(f"/api/projects/{pb}/packages/{bom_b}/award", headers=hb, json={"selections": {}})
    b_numbers = [p["po"] for p in r.json()["poNumbers"]]
    assert b_numbers[0] == "PO-2-0001"

    # Re-awarding issues fresh numbers and the decision list exposes them.
    r = client.post(f"/api/projects/{pa}/packages/{bom_a1}/award", headers=ha,
                    json={"selections": {}, "supersede": True})
    assert r.status_code == 200
    re_award = [p["po"] for p in r.json()["poNumbers"]]
    assert min(int(po.rsplit("-", 1)[1]) for po in re_award) > max(nums)
    decisions = client.get(f"/api/projects/{pa}/purchase-decisions", headers=ha).json()
    assert [p["po"] for p in decisions[0]["poNumbers"]] == re_award


def test_po_number_is_in_the_winner_email(project, monkeypatch):
    from app.services.rfq import sender as rfq_sender
    client, headers, pid = project
    bom_id, token = _ready_package(client, headers, pid, n=2)
    sent = []

    class Rec:
        mocked = True

        def send(self, to, subject, body, **kw):
            sent.append({"to": to, "subject": subject, "body": body})
            return rfq_sender.SentMessage(message_id=f"m-{len(sent)}", thread_id="t")

    monkeypatch.setattr(rfq_sender, "get_sender", lambda: Rec())
    r = client.post(f"/api/approvals/{token}")
    assert r.status_code == 200, r.text
    for p in r.json()["poNumbers"]:
        winner_mail = [m for m in sent if p["po"] in m["body"]]
        assert winner_mail, f"no email carried {p['po']}"
        assert f"PO number: {p['po']}" in winner_mail[0]["body"]


# ---------------------------------------------------------- org isolation

def test_token_from_org_a_cannot_award_in_org_b(client):
    ha = _register(client, "a@alpha-gc.com", "Alpha GC")
    hb = _register(client, "b@beta-gc.com", "Beta GC")
    pa = _project(client, ha, "Alpha Job")
    pb = _project(client, hb, "Beta Job")
    bom_a, token_a = _ready_package(client, ha, pa, n=2)
    bom_b, token_b = _ready_package(client, hb, pb, n=2)

    # Whoever clicks A's link (even B's user naming themselves) awards A's
    # package in A's org, with A's PO sequence; B's data is untouched.
    r = client.post(f"/api/approvals/{token_a}", json={"decidedByEmail": "b@beta-gc.com"})
    assert r.status_code == 200, r.text
    assert r.json()["projectId"] == pa
    assert r.json()["poNumbers"][0]["po"].startswith("PO-1-")
    assert client.get(f"/api/projects/{pb}/purchase-decisions", headers=hb).json() == []
    (d,) = client.get(f"/api/projects/{pa}/purchase-decisions", headers=ha).json()
    # B's address is not a member of A: recorded as the link, not as B.
    assert d["decidedBy"].startswith("approval-link:")
    assert d["decidedByEmail"] == "b@beta-gc.com"

    # B's own link still works in B only.
    r = client.post(f"/api/approvals/{token_b}")
    assert r.status_code == 200 and r.json()["projectId"] == pb
    assert r.json()["poNumbers"][0]["po"] == "PO-2-0001"
    assert len(client.get(f"/api/projects/{pa}/purchase-decisions", headers=ha).json()) == 1
