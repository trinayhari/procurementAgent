"""Need-by dates: set on the project, inherited by RFQs, quoted to suppliers.

The PM's "pour is the 21st" has to reach the RFQ email, the follow-up nudge
and the sent notice, so the date lives on the project (editable) and is
copied onto each RFQ when it is drafted (editable per RFQ, so a later change
to the project does not silently rewrite a request already sent).
"""
from app.core.dates import humanize, parse_iso_date
from app.db import SessionLocal
from app.repositories import projects as projects_repo
from app.services import notify
from app.services.rfq import followups
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search


def test_iso_date_helpers():
    assert parse_iso_date(" 2026-10-14 ") == "2026-10-14"
    assert parse_iso_date("") is None and parse_iso_date(None) is None
    assert humanize("2026-10-14") == "October 14, 2026"
    assert humanize("") == "" and humanize("soon") == "soon"
    try:
        parse_iso_date("10/14/2026")
    except ValueError as exc:
        assert "2026-10-14" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a non-ISO date must be rejected")


def test_project_create_accepts_and_validates_need_by(auth):
    client, headers = auth
    r = client.post("/api/projects", headers=headers, json={"name": "Riverside WTP", "needBy": "2026-10-14"})
    assert r.status_code == 201, r.text
    assert r.json()["needBy"] == "2026-10-14"
    pid = r.json()["id"]
    assert client.get(f"/api/projects/{pid}", headers=headers).json()["needBy"] == "2026-10-14"
    assert client.get("/api/projects", headers=headers).json()[0]["needBy"] == "2026-10-14"

    r = client.post("/api/projects", headers=headers, json={"name": "Bad date", "needBy": "Oct 14"})
    assert r.status_code == 422
    r = client.post("/api/projects", headers=headers, json={"name": "No date", "needBy": ""})
    assert r.status_code == 201 and r.json()["needBy"] is None


def test_project_patch_sets_and_clears_need_by(project):
    client, headers, pid = project
    r = client.patch(f"/api/projects/{pid}", headers=headers, json={"needBy": "2026-11-02"})
    assert r.status_code == 200, r.text
    assert r.json()["needBy"] == "2026-11-02"
    # Untouched fields survive a partial patch.
    assert r.json()["loc"] == "Austin, TX"
    r = client.patch(f"/api/projects/{pid}", headers=headers, json={"needBy": None, "loc": "Dallas, TX"})
    assert r.status_code == 200 and r.json()["needBy"] is None and r.json()["loc"] == "Dallas, TX"
    r = client.patch(f"/api/projects/{pid}", headers=headers, json={"needBy": "nope"})
    assert r.status_code == 422
    assert client.patch("/api/projects/missing", headers=headers, json={"needBy": None}).status_code == 404
    # A second org cannot patch it.
    other = client.post("/api/auth/register", json={"email": "x@other.com", "password": "password123", "name": "X"})
    oh = {"Authorization": f"Bearer {other.json()['accessToken']}"}
    assert client.patch(f"/api/projects/{pid}", headers=oh, json={"needBy": "2026-01-01"}).status_code == 404


def test_rfq_inherits_the_project_need_by_and_quotes_it(project):
    client, headers, pid = project
    assert client.patch(f"/api/projects/{pid}", headers=headers, json={"needBy": "2026-10-14"}).status_code == 200
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:1])
    assert rfq["needBy"] == "2026-10-14"
    assert "on site by October 14, 2026" in rfq["body"]
    # Changing the project afterwards does not rewrite the drafted RFQ.
    client.patch(f"/api/projects/{pid}", headers=headers, json={"needBy": "2026-12-01"})
    assert client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()["needBy"] == "2026-10-14"


def test_rfq_update_sets_clears_and_leaves_need_by(project):
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:1])
    assert rfq["needBy"] is None
    url = f"/api/projects/{pid}/rfqs/{rfq['id']}"
    base = {"subject": rfq["subject"], "body": rfq["body"], "recipients": rfq["recipients"]}
    r = client.put(url, headers=headers, json={**base, "needBy": "2026-10-14"})
    assert r.status_code == 200 and r.json()["needBy"] == "2026-10-14"
    # Omitted: unchanged (an older client never clears it by accident).
    r = client.put(url, headers=headers, json=base)
    assert r.status_code == 200 and r.json()["needBy"] == "2026-10-14"
    r = client.put(url, headers=headers, json={**base, "needBy": None})
    assert r.status_code == 200 and r.json()["needBy"] is None
    assert client.put(url, headers=headers, json={**base, "needBy": "14 Oct"}).status_code == 422


def test_sent_notice_and_followup_quote_the_date(project, monkeypatch):
    client, headers, pid = project
    client.patch(f"/api/projects/{pid}", headers=headers, json={"needBy": "2026-10-14"})
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:1])

    class Fake:
        name = "fake"
        notices = []

        def notify(self, db, notice):
            self.notices.append(notice)

    fake = Fake()
    notify.register(fake)
    try:
        r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
        assert r.status_code == 200, r.text
    finally:
        notify.reset()
        from app.services.notify import setup as notify_setup

        notify_setup.install()
    [sent] = [n for n in fake.notices if n.kind == "rfq.sent"]
    assert "Need by October 14, 2026" in sent.lines

    _, body = followups.draft_followup(
        {**rfq, "needBy": "2026-10-14"}, rfq["recipients"][0], 1
    )
    assert "on site by October 14, 2026" in body


def test_intake_writes_the_pm_date_onto_the_project(project):
    from app.services.inbound import intake

    client, headers, pid = project
    with SessionLocal() as db:
        org_id = projects_repo.get_row(db, client.get("/api/auth/me", headers=headers).json()["organizationId"], pid).organization_id
        result = intake.handle_request(
            db, org_id=org_id, user=None, subject="Test Project",
            text="Rev B is out. Can we get water utilities priced? Need it on site by 2026-10-21.",
            attachments=[], thread=None,
        )
        assert result.project_id == pid and result.need_by == "2026-10-21"
    assert client.get(f"/api/projects/{pid}", headers=headers).json()["needBy"] == "2026-10-21"
