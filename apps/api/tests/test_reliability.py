"""Reliability regressions: upload validation, ephemeral-file state, job/RFQ
idempotency, worker failure recording, and input validation.

Each test pins a bug found while hardening the core flow (upload → extraction
→ suppliers → RFQ → quotes → award).
"""
import io
import os
import threading
import time

import pytest
from sqlalchemy import text

from app.api.routes import documents as documents_routes
from app.api.routes import sourcing as sourcing_routes
from app.config import settings
from app.db import SessionLocal
from app.repositories import documents as documents_repo
from app.repositories import jobs as jobs_repo
from app.repositories import users as users_repo
from app.services.rfq import sender as rfq_sender
from tests.conftest import generate_rfq, make_confirmed_bom, run_supplier_search

# A tiny valid one-page PDF.
_MINI_PDF = (
    b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
)


def _upload(client, headers, filename, content, plan_type="site_plan", project_id="test-project"):
    return client.post(
        "/api/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        data={"project_id": project_id, "plan_type": plan_type},
    )


def _org_id(email="pm@example.com"):
    with SessionLocal() as db:
        return users_repo.get_by_email(db, email).organization_id


def _doc_row(doc_id):
    with SessionLocal() as db:
        return documents_repo.get(db, _org_id(), doc_id)


def _upload_dir_files():
    return set(os.listdir(settings.upload_dir)) if os.path.isdir(settings.upload_dir) else set()


# --------------------------------------------------------------- upload checks
def test_empty_upload_is_rejected_and_leaves_nothing_behind(project, monkeypatch):
    """A 0-byte file used to be accepted into 'Processing' and then flip to a
    'Failed' document with no visible reason."""
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    before = _upload_dir_files()
    r = _upload(client, headers, "empty.pdf", b"")
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()
    assert _upload_dir_files() == before  # no orphaned file
    assert client.get(f"/api/projects/{pid}/documents", headers=headers).json() == []


def test_corrupt_pdf_is_rejected_at_upload(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    r = _upload(client, headers, "broken.pdf", b"%PDF-1.4 garbage")
    assert r.status_code == 400
    assert "Could not read this PDF" in r.json()["detail"]
    assert client.get(f"/api/projects/{pid}/documents", headers=headers).json() == []


def test_spreadsheet_in_a_plan_slot_is_rejected_but_allowed_as_additional_doc(project, monkeypatch):
    """Nothing can be extracted from an .xlsx, so a BOM slot must refuse it up
    front instead of creating a document doomed to 'Failed'."""
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    r = _upload(client, headers, "takeoff.xlsx", b"PK\x03\x04 not really", plan_type="site_plan")
    assert r.status_code == 400
    assert "additional document" in r.json()["detail"]
    r = _upload(client, headers, "takeoff.xlsx", b"PK\x03\x04 not really", plan_type="other")
    assert r.status_code == 201
    assert r.json()["status"] == "Analyzed"  # stored, nothing to extract


def test_webp_uploads_are_accepted(project, monkeypatch):
    """The upload picker offers .webp; the backend allowlist used to refuse it."""
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    r = _upload(client, headers, "scan.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    assert r.status_code == 201, r.text
    assert r.json()["pages"] == 1


# ------------------------------------------------------- ephemeral file state
def test_missing_stored_file_is_flagged_and_explained(project, monkeypatch):
    """Uploads live on local disk, which is ephemeral on some hosts. When the
    file is gone the document must say so (fileMissing) and the file endpoints
    must answer 410 with a re-upload hint rather than a generic 404."""
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload(client, headers, "plan.pdf", _MINI_PDF).json()["id"]

    listed = client.get(f"/api/projects/{pid}/documents", headers=headers).json()
    assert listed[0]["hasFile"] is True and listed[0]["fileMissing"] is False
    assert client.get(f"/api/documents/{doc_id}/preview", headers=headers).status_code == 200

    os.remove(_doc_row(doc_id).source_path)

    listed = client.get(f"/api/projects/{pid}/documents", headers=headers).json()
    assert listed[0]["fileMissing"] is True
    assert client.get(f"/api/documents/{doc_id}", headers=headers).json()["fileMissing"] is True
    for path in (f"/api/documents/{doc_id}/preview", f"/api/documents/{doc_id}/file-url"):
        r = client.get(path, headers=headers)
        assert r.status_code == 410, path
        assert "re-upload" in r.json()["detail"]
    r = client.post(f"/api/documents/{doc_id}/analyze", headers=headers)
    assert r.status_code == 410

    # A document that never had a file (custom BOM) is not "missing" one.
    r = client.post("/api/documents/manual", headers=headers, json={"name": "BOM", "projectId": pid})
    assert r.json()["fileMissing"] is False
    assert client.get(f"/api/documents/{r.json()['id']}/preview", headers=headers).status_code == 404


def test_reanalyze_rejects_a_document_still_processing(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload(client, headers, "plan.pdf", _MINI_PDF).json()["id"]
    # The pipeline is stubbed out, so the row stays in 'Processing'.
    assert _doc_row(doc_id).processing is True
    r = client.post(f"/api/documents/{doc_id}/analyze", headers=headers)
    assert r.status_code == 409
    assert "already being analyzed" in r.json()["detail"]


# ------------------------------------------------------------ demo BOM leak
def test_rfq_never_falls_back_to_the_demo_bom_for_a_real_tenant(project):
    """With demo data seeded, a real tenant's project with no extracted BOM used
    to generate an RFQ from the seed Riverside quantities — placeholder items
    nobody approved, sent to real suppliers."""
    client, headers, pid = project
    from app.repositories import reference as reference_repo

    with SessionLocal() as db:
        reference_repo.seed_reference_data(db)  # what PROCUREAI_SEED_DEMO_DATA=true does
        assert reference_repo.list_line_item_groups(db)

    bom = client.get(f"/api/projects/{pid}/packages/water/bom", headers=headers).json()
    assert bom["count"] == 0 and bom["seeded"] is False

    sids = run_supplier_search(client, headers, pid, "water")
    r = client.post(
        f"/api/projects/{pid}/packages/water/rfqs/generate",
        headers=headers,
        json={"supplier_ids": sids[:1]},
    )
    assert r.status_code == 409
    assert "No approved BOM items" in r.json()["detail"]


# --------------------------------------------------------- job idempotency
def test_search_is_idempotent_while_one_is_running(project, monkeypatch):
    """A double-click must not start a second Places crawl (and a second
    replace-all write racing the first)."""
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    started = []
    monkeypatch.setattr(sourcing_routes, "run_search_job", lambda *a, **k: started.append(a))
    # Background tasks are stubbed, so the first job stays 'running'.
    for _ in range(3):
        r = client.post(
            f"/api/projects/{pid}/packages/{bom_id}/search-suppliers",
            headers=headers,
            json={"radius_mi": 50},
        )
        assert r.status_code == 202
        assert r.json()["status"] == "searching"
    assert len(started) == 1
    with SessionLocal() as db:
        running = [j for j in jobs_repo.list_jobs(db, _org_id()) if j["status"] == "running"]
        assert len(running) == 1
    # Once it finishes, a new search can start.
    with SessionLocal() as db:
        jobs_repo.finish(db, _org_id(), running[0]["id"])
    client.post(
        f"/api/projects/{pid}/packages/{bom_id}/search-suppliers",
        headers=headers, json={"radius_mi": 50},
    )
    assert len(started) == 2


def test_ingest_is_idempotent_while_one_is_running(project, monkeypatch):
    client, headers, pid = project
    started = []
    monkeypatch.setattr(sourcing_routes, "run_ingest_job", lambda *a, **k: started.append(a))
    for _ in range(2):
        r = client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)
        assert r.status_code == 202 and r.json()["status"] == "ingesting"
    assert len(started) == 1
    st = client.get(f"/api/projects/{pid}/quotes/ingest-status", headers=headers).json()
    assert st["status"] == "ingesting"


def test_worker_records_failure_even_after_a_database_error(project, monkeypatch):
    """A DB error inside the worker leaves the session needing a rollback; the
    failure write itself then raised and the job was pinned in 'running' with
    nothing in the exception queue (and the UI spinning forever)."""
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)

    def boom(db, *a, **k):
        db.execute(text("INSERT INTO background_jobs (id) VALUES ('x')"))  # NOT NULL violations

    monkeypatch.setattr(sourcing_routes.sourcing_repo, "replace_found_suppliers", boom)
    r = client.post(
        f"/api/projects/{pid}/packages/{bom_id}/search-suppliers",
        headers=headers, json={"radius_mi": 50},
    )
    assert r.status_code == 202
    found = client.get(
        f"/api/projects/{pid}/suppliers/found?package={bom_id}", headers=headers
    ).json()
    assert found["status"] == "error"
    assert found["error"]
    errors = client.get("/api/jobs?status=error", headers=headers).json()
    assert len(errors) == 1


# ------------------------------------------------------ RFQ send concurrency
def test_overlapping_sends_email_each_supplier_once(project, monkeypatch):
    """Two overlapping sends (two tabs / a replayed request) both read 'Draft'
    and both emailed every supplier. A per-RFQ lock turns the second into a 409."""
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:3])
    n_recipients = len(rfq["recipients"])
    assert n_recipients >= 2

    sent = []
    gate = threading.Event()

    class SlowSender:
        def send(self, to, subject, body, **kw):
            gate.wait(5)  # hold the first send open until the second request is in
            sent.append(to)
            return rfq_sender.SentMessage(message_id=f"m-{len(sent)}", thread_id="t")

    monkeypatch.setattr(rfq_sender, "get_sender", lambda: SlowSender())

    results = []

    def go():
        results.append(client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers))

    t1 = threading.Thread(target=go)
    t2 = threading.Thread(target=go)
    t1.start()
    time.sleep(0.3)  # t1 is inside the sender, holding the lock
    t2.start()
    t2.join(5)
    gate.set()
    t1.join(10)

    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409], [(r.status_code, r.text) for r in results]
    assert len(sent) == n_recipients  # every supplier emailed exactly once
    final = client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()
    assert final["status"] == "Awaiting"


# ------------------------------------------------------------ input validation
def test_project_name_must_not_be_blank(auth):
    client, headers = auth
    for name in ("", "   "):
        r = client.post("/api/projects", headers=headers, json={"name": name, "loc": "x"})
        assert r.status_code == 422, name
    r = client.post("/api/projects", headers=headers, json={"name": "  Dam  ", "loc": " Boulder, CO "})
    assert r.status_code == 201
    assert r.json()["name"] == "Dam" and r.json()["loc"] == "Boulder, CO"
    r = client.post("/api/projects", headers=headers, json={"name": "x" * 201})
    assert r.status_code == 422


def test_rfq_recipients_must_have_valid_emails(project):
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:1])
    bad = {"subject": "s", "body": "b", "recipients": [{"name": "X", "email": "not-an-email"}]}
    r = client.put(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers, json=bad)
    assert r.status_code == 422
    assert "not a valid email" in r.text
    good = {"subject": "s", "body": "b", "recipients": [{"name": "X", "email": " x@example.com "}]}
    r = client.put(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers, json=good)
    assert r.status_code == 200
    assert r.json()["recipients"][0]["email"] == "x@example.com"


@pytest.mark.parametrize("plan_type", ["site_plan", "other"])
def test_valid_pdf_upload_still_works(project, monkeypatch, plan_type):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    r = _upload(client, headers, "plan.pdf", _MINI_PDF, plan_type=plan_type)
    assert r.status_code == 201, r.text
    assert r.json()["pages"] == 1


# ------------------------------------------------------------ document ids
def test_document_ids_are_never_reused_after_delete(project):
    """Ids were 'upload-{max(seq)+1}': deleting the newest document handed its
    id to the next one, so RFQ attachment references and signed file tokens
    minted for the deleted document silently pointed at the new one."""
    client, headers, pid = project
    r = client.post("/api/documents/manual", headers=headers, json={"name": "A", "projectId": pid})
    first = r.json()["id"]
    assert client.delete(f"/api/documents/{first}", headers=headers).status_code == 204
    r = client.post("/api/documents/manual", headers=headers, json={"name": "B", "projectId": pid})
    second = r.json()["id"]
    assert second != first
    assert client.get(f"/api/documents/{first}", headers=headers).status_code == 404


def test_concurrent_document_creates_do_not_collide(project):
    """Two creates computing the same seq used to fail the second with a 500
    (UNIQUE on seq); it now retries with the next number."""
    client, headers, pid = project
    codes = []

    def go(i):
        r = client.post("/api/documents/manual", headers=headers, json={"name": f"B{i}", "projectId": pid})
        codes.append(r.status_code)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert codes == [201] * 6
    ids = [d["id"] for d in client.get(f"/api/projects/{pid}/documents", headers=headers).json()]
    assert len(ids) == len(set(ids)) == 6


# ------------------------------------------ custom-package compare + award
def test_compare_and_award_accept_a_custom_package_by_name(project):
    """The Quotes table groups by label; for a custom BOM / trade the label is
    the document's name, which the compare route couldn't map back to a key
    ('No quotes to compare for package')."""
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid, name="Hydrants Package")
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:2])
    client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    client.post(f"/api/projects/{pid}/quotes/ingest", headers=headers)

    # Quote rows now carry the package key next to the label.
    rows = client.get(f"/api/projects/{pid}/quotes", headers=headers).json()
    assert rows and all(q["package"] == bom_id and q["pkg"] == "Hydrants Package" for q in rows)

    by_name = client.get(f"/api/projects/{pid}/packages/Hydrants%20Package/line-comparison", headers=headers)
    assert by_name.status_code == 200, by_name.text
    by_id = client.get(f"/api/projects/{pid}/packages/{bom_id}/line-comparison", headers=headers)
    assert by_name.json()["lines"] == by_id.json()["lines"]
    assert by_id.json()["pkg"] == "Hydrants Package"  # label, not the document id
    assert by_id.json()["lastAward"] is None

    r = client.post(
        f"/api/projects/{pid}/packages/Hydrants%20Package/award",
        headers=headers, json={"selections": {}, "strategy": "mix"},
    )
    assert r.status_code == 200, r.text
    decisions = client.get(f"/api/projects/{pid}/purchase-decisions", headers=headers).json()
    assert decisions[0]["package"] == bom_id and decisions[0]["packageLabel"] == "Hydrants Package"

    # The comparison now reports the award so the UI can guard a re-award.
    last = client.get(f"/api/projects/{pid}/packages/{bom_id}/line-comparison", headers=headers).json()["lastAward"]
    assert last and last["decidedByEmail"] == "pm@example.com" and last["poCount"] >= 1


# -------------------------------------------------------- demo data gating
def test_demo_quotes_and_rfqs_are_not_served_to_other_tenants(project):
    client, headers, pid = project
    from app.repositories import reference as reference_repo

    with SessionLocal() as db:
        reference_repo.seed_reference_data(db)
        assert reference_repo.list_demo_quotes(db)
    assert client.get(f"/api/projects/{pid}/quotes", headers=headers).json() == []
    assert client.get(f"/api/projects/{pid}/rfqs", headers=headers).json() == []
    assert client.get(f"/api/projects/{pid}/rfq-folders", headers=headers).json() == []
    assert client.get(f"/api/projects/{pid}/line-items", headers=headers).json() == []
    r = client.get(f"/api/projects/{pid}/packages/Water%20Utilities/comparison", headers=headers)
    assert r.status_code == 404


def test_pending_review_count_ignores_seed_documents(project):
    """Seed/demo documents have no BOM of their own; they used to inflate the
    'confirm the extracted BOM on N documents first' count for every package."""
    client, headers, pid = project
    from app.models.document import Document
    from app.repositories import reference as reference_repo

    with SessionLocal() as db:
        reference_repo.seed_reference_data(db)
        for i in range(3):  # seed-style rows: no plan type
            db.add(Document(
                organization_id=_org_id(), seq=1000 + i, id=f"seed-{i}", project_id=pid,
                name=f"Seed {i}", type="Plan Set", date="Jan 01, 2026", status="Analyzed",
                status_tone="success", items="42", pages=1, processing=False, has_file=False,
                plan_type=None, reviewed=False, edited=False,
            ))
        db.commit()
    bom = client.get(f"/api/projects/{pid}/packages/water/bom", headers=headers).json()
    assert bom["pendingReview"] == 0 and bom["count"] == 0


# ------------------------------------------------------------- RFQ details
def test_sent_rfq_reports_sent_at(project):
    client, headers, pid = project
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    rfq = generate_rfq(client, headers, pid, bom_id, sids[:1])
    assert rfq["sentAt"] is None and rfq["time"] == "—"
    sent = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers).json()
    assert sent["sentAt"] and sent["time"] != "—"


def test_rfq_intro_does_not_double_the_full_stop():
    from app.services.rfq import generator

    class Buyer:
        name = "Jordan Mills"
        company = "Meridian Civil Co."

    assert generator._buyer_intro(Buyer()) == "My name is Jordan Mills with Meridian Civil Co."
    Buyer.company = "Acme"
    assert generator._buyer_intro(Buyer()) == "My name is Jordan Mills with Acme."
