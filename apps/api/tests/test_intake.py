"""Conversational intake: a known user emails plans, the agent files them,
starts extraction and replies in the thread.

The Resend webhook (which builds InboundEmail rows) is not exercised here;
rows are constructed directly with attachments already in storage, exactly
as the webhook would leave them.
"""
import json
import os
import tempfile
import uuid
from datetime import date, datetime, timezone

import pytest

from app.api.routes import documents as documents_routes
from app.config import settings
from app.db import SessionLocal
from app.models.inbound_email import InboundEmail
from app.repositories import documents as documents_repo
from app.repositories import events as events_repo
from app.repositories import projects as projects_repo
from app.repositories import users as users_repo
from app.services import documents_intake, notify, storage
from app.services.inbound import intake

# A tiny valid one-page PDF (same as tests/test_uploads.py).
_MINI_PDF = (
    b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
)


# ------------------------------------------------------------------ helpers
def store_fixture(filename: str, content: bytes = _MINI_PDF) -> dict:
    """Put `content` in storage the way the webhook does and return the
    attachment dict an InboundEmail row carries."""
    suffix = os.path.splitext(filename)[1]
    fd, tmp = tempfile.mkstemp(prefix="procureai-test-att-", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(content)
    stored = storage.persist_temp(storage.StoredFile(locator=tmp, sha256="", size=len(content)), filename)
    mime = "application/pdf" if suffix == ".pdf" else "application/octet-stream"
    return {"filename": filename, "mimeType": mime, "size": stored.size, "locator": stored.locator}


def make_inbound(db, *, from_email, subject, text="", attachments=None, kind="unknown", org_id=None):
    row = InboundEmail(
        id=uuid.uuid4().hex,
        organization_id=org_id,
        provider_message_id=f"resend-{uuid.uuid4().hex[:8]}",
        rfc_message_id=f"<{uuid.uuid4().hex}@example.com>",
        from_email=from_email,
        from_name="PM",
        to_addresses=json.dumps(["intake@in.example.com"]),
        subject=subject,
        text=text,
        attachments=json.dumps(attachments or []),
        kind=kind,
        received_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class RecordingNotifier:
    name = "test-recorder"

    def __init__(self):
        self.notices = []

    def notify(self, db, notice):
        self.notices.append(notice)


@pytest.fixture()
def recorder():
    notify.reset()
    rec = RecordingNotifier()
    notify.register(rec)
    yield rec
    notify.reset()


@pytest.fixture()
def pipeline(monkeypatch):
    """Stub the extraction pipeline and run the intake scheduler inline, so a
    test can assert extraction was kicked off without waiting on a thread."""
    calls = []
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a: calls.append(a))
    monkeypatch.setattr(documents_intake, "_run_in_thread", lambda fn, *a: fn(*a))
    return calls


def _org_of(db, email="pm@example.com"):
    return users_repo.get_by_email(db, email).organization_id


# -------------------------------------------------------------- attribution
def test_attribute_known_user_sets_org(auth):
    with SessionLocal() as db:
        row = make_inbound(db, from_email="PM@Example.com", subject="Riverside")
        assert intake.attribute(db, row) is True
        assert row.organization_id == _org_of(db)


def test_attribute_unknown_sender(auth):
    with SessionLocal() as db:
        row = make_inbound(db, from_email="stranger@else.com", subject="Hi")
        assert intake.attribute(db, row) is False
        assert row.organization_id is None


# ------------------------------------------------------------ parsing bits
def test_parse_need_by_forms():
    today = date(2026, 9, 21)
    assert intake.parse_need_by("need these by the 14th", today) == "2026-10-14"
    assert intake.parse_need_by("before Oct 14 please", today) == "2026-10-14"
    assert intake.parse_need_by("need it by 10/14", today) == "2026-10-14"
    assert intake.parse_need_by("due 10/14/2027", today) == "2027-10-14"
    assert intake.parse_need_by("deadline: October 3rd, 2027", today) == "2027-10-03"
    assert intake.parse_need_by("we have 3 suppliers by 3 pm", today) is None
    assert intake.parse_need_by("", today) is None


def test_infer_plan_type():
    assert intake.infer_plan_type("C-101 site plan.pdf") == "site_plan"
    assert intake.infer_plan_type("E-201.pdf") == "electrical_plan"
    assert intake.infer_plan_type("Building-Set.pdf") == "building_plan"
    assert intake.infer_plan_type("Approval Set.pdf", "electrical plans attached") == "electrical_plan"
    assert intake.infer_plan_type("plans.pdf", "site and electrical") == "other"
    assert intake.infer_plan_type("schedule.xlsx", "site plan") == "other"
    assert intake.infer_plan_type("photo.jpg", "grading") == "site_plan"


def test_clean_subject_strips_reply_prefixes():
    assert intake.clean_subject("Re: FW: Riverside WTP - plans.") == "Riverside WTP - plans"


# --------------------------------------------------------- project resolve
def test_existing_project_matched_by_subject(project, recorder, pipeline):
    client, headers, pid = project
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="Re: test project",
                           text="one more note", kind="intake", org_id=org_id)
        intake.handle(db, row)
        db.refresh(row)
        assert row.project_id == pid
        assert row.processed_at is not None and row.error is None
        assert len(projects_repo.list_projects(db, org_id)) == 1


def test_existing_project_matched_by_name_in_body(project, recorder, pipeline):
    client, headers, pid = project
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="plans",
                           text="Attached are the plans for Test Project.", kind="intake", org_id=org_id)
        intake.handle(db, row)
        db.refresh(row)
        assert row.project_id == pid


def test_new_project_created_from_subject(auth, recorder, pipeline):
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="Fwd: Riverside WTP",
                           text="Need these by the 14th.", kind="intake", org_id=org_id)
        intake.handle(db, row)
        db.refresh(row)
        projects = projects_repo.list_projects(db, org_id)
        assert [p["name"] for p in projects] == ["Riverside WTP"]
        assert row.project_id == projects[0]["id"]
        assert projects[0]["loc"] == "TBD"
        titles = [e["title"] for e in events_repo.list_for_project(db, org_id, row.project_id)]
        assert "Project created" in titles
    assert recorder.notices[-1].meta["projectCreated"] is True


def test_llm_resolution_is_used_when_configured(auth, recorder, pipeline, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        intake, "_llm_resolve",
        lambda projects, subject, text: {
            "project_name": "Northside Depot", "is_existing": False, "existing_project_id": None,
            "location": "Denver, CO", "need_by": "2026-11-30", "notes": "",
        },
    )
    with SessionLocal() as db:
        org_id = _org_of(db)
        resolved = intake.resolve_project(db, org_id, "plans for the depot job", "see attached")
        assert resolved.created is True
        assert resolved.name == "Northside Depot"
        assert resolved.need_by == "2026-11-30"
        assert projects_repo.get_project(db, org_id, resolved.project_id)["loc"] == "Denver, CO"


def test_llm_failure_falls_back_to_subject(auth, recorder, pipeline, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("no network in tests")

    from app.services.extraction import vision

    monkeypatch.setattr(vision, "_client", lambda: Boom())
    with SessionLocal() as db:
        org_id = _org_of(db)
        resolved = intake.resolve_project(db, org_id, "Re: Depot job", "")
        assert resolved.created is True and resolved.name == "Depot job"


# ------------------------------------------------------------- attachments
def test_attachment_becomes_document_and_extraction_starts(project, recorder, pipeline):
    client, headers, pid = project
    att = store_fixture("C-101 Site Plan.pdf")
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="Test Project",
                           text="Site plans attached, need by Oct 14.", attachments=[att],
                           kind="intake", org_id=org_id)
        intake.handle(db, row)
        db.refresh(row)
        assert row.error is None and row.processed_at is not None
        docs = documents_repo.list_for_project(db, org_id, pid)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["planType"] == "site_plan"
        assert doc["name"] == "C-101 Site Plan"
        assert doc["pages"] == 1
        assert doc["status"] == "Processing"
        assert doc["checksum"]
        stored = documents_repo.get(db, org_id, doc["id"])
        assert stored.source_path == att["locator"]
        titles = [e["title"] for e in events_repo.list_for_project(db, org_id, pid)]
        assert f"Plans uploaded: {doc['name']}" in titles
    # The pipeline was scheduled with the same arguments an upload passes.
    assert pipeline == [(org_id, doc["id"], att["locator"], "site_plan")]
    # And the customer heard back in their thread.
    notice = recorder.notices[-1]
    assert notice.kind == "intake.received"
    assert notice.project_id == pid
    assert notice.title == "Got it: Test Project"
    assert notice.thread == notify.ThreadRef(
        channel="email", email_message_id=row.rfc_message_id,
        email_address="pm@example.com", email_subject="Test Project",
    )
    assert any(line.startswith("C-101 Site Plan.pdf: Site Plan, 1 page") for line in notice.lines)
    assert "Need by: 2026-10-14" in notice.lines
    assert notice.lines[-1] == "Drafting the bill of materials now, I'll reply here when it's ready."
    assert not any(chr(0x2014) in line for line in [notice.title, *notice.lines])


def test_two_files_same_slot_do_not_replace_each_other(project, recorder, pipeline):
    client, headers, pid = project
    a = store_fixture("E-101.pdf")
    b = store_fixture("E-102.pdf")
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="Test Project",
                           attachments=[a, b], kind="intake", org_id=org_id)
        intake.handle(db, row)
        docs = documents_repo.list_for_project(db, org_id, pid)
        assert sorted(d["planType"] for d in docs) == ["electrical_plan", "other"]


def test_spreadsheet_goes_to_other_and_is_not_extracted(project, recorder, pipeline):
    client, headers, pid = project
    att = store_fixture("site schedule.xlsx", b"not,really,a,sheet\n")
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="Test Project",
                           attachments=[att], kind="intake", org_id=org_id)
        intake.handle(db, row)
        db.refresh(row)
        assert row.error is None
        docs = documents_repo.list_for_project(db, org_id, pid)
        assert docs[0]["planType"] == "other" and docs[0]["status"] == "Analyzed"
    assert pipeline == []
    assert recorder.notices[-1].lines[-1].startswith("Filed on the project")


# --------------------------------------------------------------- no files
def test_message_without_attachment_is_logged_as_note(project, recorder, pipeline):
    client, headers, pid = project
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="Test Project",
                           text="Addendum 2 moves the pour to Friday.", kind="intake", org_id=org_id)
        intake.handle(db, row)
        db.refresh(row)
        assert row.project_id == pid and row.processed_at is not None
        events = events_repo.list_for_project(db, org_id, pid)
        assert events[0]["title"] == "Note from PM: Addendum 2 moves the pour to Friday."
    notice = recorder.notices[-1]
    assert notice.kind == "intake.noted" and notice.project_id == pid
    assert notice.thread.channel == "email" and notice.thread.email_message_id == row.rfc_message_id
    assert pipeline == []


# ---------------------------------------------------------------- failures
def test_failure_is_recorded_and_not_raised(project, recorder, pipeline, monkeypatch):
    client, headers, pid = project

    def explode(*a, **k):
        raise RuntimeError("storage is on fire")

    monkeypatch.setattr(intake, "resolve_project", explode)
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="Test Project",
                           kind="intake", org_id=org_id)
        intake.handle(db, row)  # must not raise
        db.refresh(row)
        assert row.processed_at is None
        assert "storage is on fire" in row.error
        assert row.attempts == 1
        intake.handle(db, row)
        db.refresh(row)
        assert row.attempts == 2
    assert recorder.notices == []


def test_handle_is_idempotent_on_processed_at(project, recorder, pipeline):
    client, headers, pid = project
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="Test Project",
                           text="note", kind="intake", org_id=org_id)
        intake.handle(db, row)
        assert len(recorder.notices) == 1
        intake.handle(db, row)
        assert len(recorder.notices) == 1
        notes = [e for e in events_repo.list_for_project(db, org_id, pid) if e["title"].startswith("Note from")]
        assert len(notes) == 1


def test_dispatcher_routes_known_sender_to_intake(project, recorder, pipeline, monkeypatch):
    from app.services import inbound
    from app.services.inbound import rfq_replies

    monkeypatch.setattr(rfq_replies, "attribute", lambda db, msg: False)
    client, headers, pid = project
    with SessionLocal() as db:
        row = make_inbound(db, from_email="pm@example.com", subject="Test Project", text="hello")
        inbound.handle(db, row)
        db.refresh(row)
        assert row.kind == "intake" and row.project_id == pid and row.processed_at is not None


# ------------------------------------------------------------------ routes
def _upload(client, headers, pid, filename="plan.pdf"):
    import io

    r = client.post(
        "/api/documents", headers=headers,
        files={"file": (filename, io.BytesIO(_MINI_PDF), "application/pdf")},
        data={"project_id": pid, "plan_type": "other"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_intake_test_route_runs_the_flow(project, recorder, pipeline):
    client, headers, pid = project
    doc_id = _upload(client, headers, pid, "E-301 lighting.pdf")
    r = client.post(
        "/api/intake/test", headers=headers,
        json={"subject": "Harbor Substation", "text": "Electrical set, need by 11/02.", "attachments": [doc_id]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["projectCreated"] is True
    assert body["needBy"].endswith("-11-02")
    assert [d["planType"] for d in body["documents"]] == ["electrical_plan"]
    assert "Harbor Substation (new project): 1 file" in body["summary"]
    with SessionLocal() as db:
        org_id = _org_of(db)
        new_doc = documents_repo.get(db, org_id, body["documents"][0]["id"])
        original = documents_repo.get(db, org_id, doc_id)
        # The original stays where it was; the intake got its own copy.
        assert original is not None and new_doc.source_path != original.source_path
        assert os.path.exists(new_doc.source_path) and os.path.exists(original.source_path)
    # A test run has no thread, so the notice carries none.
    assert recorder.notices[-1].thread is None
    assert pipeline and pipeline[-1][3] == "electrical_plan"


def test_intake_test_route_rejects_foreign_document(project, recorder, pipeline):
    client, headers, pid = project
    r = client.post("/api/intake/test", headers=headers,
                    json={"subject": "x", "text": "", "attachments": ["upload-999-abcdef"]})
    assert r.status_code == 404


def test_list_project_intake(project, recorder, pipeline):
    client, headers, pid = project
    att = store_fixture("A-101.pdf")
    with SessionLocal() as db:
        org_id = _org_of(db)
        row = make_inbound(db, from_email="pm@example.com", subject="Test Project",
                           text="Building set attached.", attachments=[att], kind="intake", org_id=org_id)
        intake.handle(db, row)
        # A row from another org's project must never show up.
        make_inbound(db, from_email="pm@example.com", subject="Other", kind="intake", org_id="other-org")
    r = client.get(f"/api/projects/{pid}/intake", headers=headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["subject"] == "Test Project"
    assert rows[0]["fromEmail"] == "pm@example.com"
    assert rows[0]["attachments"] == 1
    assert rows[0]["summary"] == "1 file: A-101.pdf"
    assert rows[0]["processedAt"]
    assert client.get("/api/projects/nope/intake", headers=headers).status_code == 404


# --------------------------------------------------- upload route refactor
def test_upload_route_still_attaches_through_the_service(project, pipeline):
    client, headers, pid = project
    doc_id = _upload(client, headers, pid, "site-plan.pdf")
    with SessionLocal() as db:
        org_id = _org_of(db)
        doc = documents_repo.get(db, org_id, doc_id)
        assert doc.plan_type == "other" and doc.pages == 1 and doc.has_file
        titles = [e["title"] for e in events_repo.list_for_project(db, org_id, pid)]
        assert "Document uploaded: site-plan" in titles
    # BackgroundTasks ran the (stubbed) pipeline after the response.
    assert pipeline == [(org_id, doc_id, doc.source_path, "other")]
