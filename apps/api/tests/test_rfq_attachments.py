"""User-selected document attachments on outgoing RFQ emails.

Attachment ids are validated at save (org/project ownership, has_file, size
budget) and hydrated into real bytes at send. A document deleted after save is
skipped, not fatal. The attachment-free path sends a plain-text message.
"""
import io
import base64

import pytest

from app.api.routes import documents as documents_routes
from app.services.rfq import generator
from app.services.rfq import sender as rfq_sender
from tests.conftest import make_confirmed_bom, run_supplier_search, generate_rfq

_MINI_PDF = (
    b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
)


class _Recorder:
    """Fake sender recording every send() including its attachments."""

    mocked = True

    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, *, from_addr, cc=None, thread_id=None,
             in_reply_to=None, attachments=None):
        self.sent.append({"to": to, "body": body, "attachments": attachments})
        return rfq_sender.SentMessage(
            message_id=f"rec-{len(self.sent)}", thread_id="t"
        )


def _upload_doc(client, headers, pid, filename="site-plan.pdf"):
    """Upload a real file (extraction pipeline stubbed out); returns the doc id."""
    r = client.post(
        "/api/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(_MINI_PDF), "application/pdf")},
        data={"project_id": pid, "plan_type": "other"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _draft_rfq(client, headers, pid):
    bom_id = make_confirmed_bom(client, headers, pid)
    sids = run_supplier_search(client, headers, pid, bom_id)
    return generate_rfq(client, headers, pid, bom_id, sids[:2])


def _save(client, headers, pid, rfq, attachment_ids):
    return client.put(
        f"/api/projects/{pid}/rfqs/{rfq['id']}",
        headers=headers,
        json={
            "subject": rfq["subject"],
            "body": rfq["body"],
            "recipients": rfq["recipients"],
            "attachment_ids": attachment_ids,
        },
    )


def test_save_and_send_with_attachment(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload_doc(client, headers, pid)
    rfq = _draft_rfq(client, headers, pid)

    r = _save(client, headers, pid, rfq, [doc_id])
    assert r.status_code == 200, r.text
    saved = r.json()
    assert [a["documentId"] for a in saved["attachments"]] == [doc_id]

    recorder = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: recorder)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text

    # Every recipient got the same hydrated attachment bytes.
    assert len(recorder.sent) == 2
    for m in recorder.sent:
        (att,) = m["attachments"]
        assert att.content == _MINI_PDF
        assert att.filename.endswith(".pdf")


def test_send_without_attachments_passes_none(project, monkeypatch):
    client, headers, pid = project
    rfq = _draft_rfq(client, headers, pid)
    recorder = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: recorder)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    assert all(m["attachments"] is None for m in recorder.sent)


def test_save_rejects_foreign_project_document(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    # A second project in the SAME org — its docs still must not attach to the
    # first project's RFQ.
    r = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "Second Project", "loc": "Austin, TX", "type": "Commercial"},
    )
    other_pid = r.json()["id"]
    foreign_doc = _upload_doc(client, headers, other_pid)
    rfq = _draft_rfq(client, headers, pid)

    r = _save(client, headers, pid, rfq, [foreign_doc])
    assert r.status_code == 400
    assert "not found on this project" in r.json()["detail"]


def test_save_rejects_fileless_document(project):
    client, headers, pid = project
    rfq = _draft_rfq(client, headers, pid)
    # A custom BOM is a document with no file — not attachable.
    bom_id = make_confirmed_bom(client, headers, pid, name="No File BOM")
    r = _save(client, headers, pid, rfq, [bom_id])
    assert r.status_code == 400
    assert "no attachable file" in r.json()["detail"]


def test_save_rejects_oversized_attachments(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload_doc(client, headers, pid)
    rfq = _draft_rfq(client, headers, pid)

    from app.api.routes import sourcing as sourcing_routes

    monkeypatch.setattr(sourcing_routes, "_MAX_ATTACHMENT_TOTAL_BYTES", 10)
    r = _save(client, headers, pid, rfq, [doc_id])
    assert r.status_code == 400
    # The message derives its number from the (patched) constant, so assert the
    # semantic marker rather than a hardcoded size.
    assert "email limit" in r.json()["detail"]


def test_save_without_attachment_ids_field_leaves_attachments_unchanged(
    project, monkeypatch
):
    """attachment_ids is Optional: an older client that PUTs only
    subject/body/recipients must not clear previously chosen attachments."""
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload_doc(client, headers, pid)
    rfq = _draft_rfq(client, headers, pid)
    assert _save(client, headers, pid, rfq, [doc_id]).status_code == 200

    r = client.put(
        f"/api/projects/{pid}/rfqs/{rfq['id']}",
        headers=headers,
        json={
            "subject": "Edited subject",
            "body": rfq["body"],
            "recipients": rfq["recipients"],
        },
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["subject"] == "Edited subject"
    assert [a["documentId"] for a in saved["attachments"]] == [doc_id]

    # An explicit empty list DOES clear them.
    r = _save(client, headers, pid, rfq, [])
    assert r.status_code == 200
    assert r.json()["attachments"] == []


def test_duplicate_attachment_ids_are_deduped(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload_doc(client, headers, pid)
    rfq = _draft_rfq(client, headers, pid)

    r = _save(client, headers, pid, rfq, [doc_id, doc_id])
    assert r.status_code == 200, r.text
    assert [a["documentId"] for a in r.json()["attachments"]] == [doc_id]

    # The email carries the file once, not twice.
    recorder = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: recorder)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    assert all(len(m["attachments"]) == 1 for m in recorder.sent)


def test_save_rejects_unknown_document_id(project):
    client, headers, pid = project
    rfq = _draft_rfq(client, headers, pid)
    r = _save(client, headers, pid, rfq, ["no-such-document"])
    assert r.status_code == 400
    assert "not found on this project" in r.json()["detail"]


def test_storage_size_edges(tmp_path):
    """size() feeds the attachment budget — unknowns are None, never a crash."""
    from app.services import storage

    assert storage.size(None) is None
    assert storage.size("") is None
    assert storage.size(str(tmp_path / "missing.pdf")) is None
    p = tmp_path / "plan.pdf"
    p.write_bytes(_MINI_PDF)
    assert storage.size(str(p)) == len(_MINI_PDF)


def test_deleted_attachment_is_skipped_at_send(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload_doc(client, headers, pid)
    rfq = _draft_rfq(client, headers, pid)
    assert _save(client, headers, pid, rfq, [doc_id]).status_code == 200

    # The document disappears between save and send.
    assert client.delete(f"/api/documents/{doc_id}", headers=headers).status_code == 204

    recorder = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: recorder)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text  # send still goes out
    assert all(m["attachments"] is None for m in recorder.sent)
    # The stored attachment list is reconciled: the UI must not present the
    # skipped document as if recipients received it.
    assert r.json()["attachments"] == []


# ------------------------------------------------------ attachment payloads
def test_build_attachments_is_empty_without_attachments():
    assert rfq_sender.build_attachments(None) == []
    assert rfq_sender.build_attachments([]) == []


def test_build_attachments_encodes_content_and_types_pdfs():
    att = rfq_sender.EmailAttachment(filename="plan.pdf", content=_MINI_PDF)
    [part] = rfq_sender.build_attachments([att])
    assert part["filename"] == "plan.pdf"
    assert part["content_type"] == "application/pdf"
    assert base64.b64decode(part["content"]) == _MINI_PDF


def test_build_attachments_unknown_extension_falls_back_to_octet_stream():
    att = rfq_sender.EmailAttachment(filename="takeoff.zz9", content=b"\x00\x01\x02")
    [part] = rfq_sender.build_attachments([att])
    assert part["content_type"] == "application/octet-stream"
    assert part["filename"] == "takeoff.zz9"
    assert base64.b64decode(part["content"]) == b"\x00\x01\x02"


def test_build_attachments_preserves_non_application_mime_types():
    """Every allowed upload type must keep its real MIME type: a .png is
    image/png, not application/png."""
    cases = [
        ("photo.png", b"\x89PNG\r\n", "image/png"),
        ("takeoff.csv", b"a,b\n1,2\n", "text/csv"),
        ("scan.jpg", b"\xff\xd8\xff", "image/jpeg"),
    ]
    for filename, content, expected in cases:
        att = rfq_sender.EmailAttachment(filename=filename, content=content)
        [part] = rfq_sender.build_attachments([att])
        assert part["content_type"] == expected, filename
        assert base64.b64decode(part["content"]) == content


def test_sent_filename_borrows_extension_only_when_name_has_none(
    project, monkeypatch
):
    """Display names with dots ("Rev 2.1 Plans") are NOT treated as extensions;
    a name without one borrows the stored file's suffix so mail clients can
    type the attachment."""
    from app.db import SessionLocal
    from app.repositories import documents as documents_repo

    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload_doc(client, headers, pid)
    rfq = _draft_rfq(client, headers, pid)

    # Rename the doc to a display name whose only dot is mid-name — the old
    # '"." in name' check wrongly treated it as already having an extension.
    with SessionLocal() as db:
        row = db.query(documents_repo.Document).get(doc_id)
        org_id = row.organization_id
        documents_repo.update_status(db, org_id, doc_id, name="Rev 2.1 Plans")

    assert _save(client, headers, pid, rfq, [doc_id]).status_code == 200
    recorder = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: recorder)
    assert (
        client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers).status_code
        == 200
    )
    (att,) = recorder.sent[0]["attachments"]
    # splitext sees no extension on "Rev 2.1 Plans", so the stored file's
    # ".pdf" is borrowed and mail clients can type the attachment.
    assert att.filename == "Rev 2.1 Plans.pdf"


def test_storage_size_s3_head(monkeypatch):
    """S3 branch of storage.size(): ContentLength on success, None on failure —
    the attachment budget must treat None as un-attachable, never 0."""
    from app.services import storage

    class FakeS3:
        def head_object(self, Bucket, Key):
            assert (Bucket, Key) == ("bucket", "key.pdf")
            return {"ContentLength": 123}

    class BrokenS3:
        def head_object(self, Bucket, Key):
            raise RuntimeError("no auth")

    monkeypatch.setattr(storage, "_s3", lambda: FakeS3())
    assert storage.size("s3://bucket/key.pdf") == 123
    monkeypatch.setattr(storage, "_s3", lambda: BrokenS3())
    assert storage.size("s3://bucket/key.pdf") is None


def test_build_attachments_strips_control_chars_from_filename():
    """A crafted upload filename must not inject mail headers via
    Content-Disposition (CRLF stripped before the payload is built)."""
    att = rfq_sender.EmailAttachment(
        filename="plans\r\nBcc: x@evil.com.pdf", content=b"x"
    )
    [part] = rfq_sender.build_attachments([att])
    assert "\r" not in part["filename"] and "\n" not in part["filename"]
    assert part["filename"] == "plansBcc: x@evil.com.pdf"


def test_subject_control_chars_are_stripped_before_sending(monkeypatch):
    """Subject carries user-influenced text (trade names, edited subjects):
    CRLF must never become a header boundary."""
    from app.services.email import agentmail_client
    from tests.agentmail_fakes import FakeAgentMail

    fake = FakeAgentMail()
    monkeypatch.setattr(agentmail_client, "get_client", lambda: fake)
    rfq_sender.AgentMailSender("acme@agentmail.to").send(
        "a@b.com", "Bid Request: Drywall\r\nBcc: x@evil.com", "Body", from_addr="acme@agentmail.to"
    )
    assert fake.sent[0]["subject"] == "Bid Request: DrywallBcc: x@evil.com"
    assert fake.sent[0]["to"] == ["a@b.com"] and "cc" not in fake.sent[0]


# ------------------------------------------- attachment note (EBUG-20/28)

_OLD_NOTE = "Please review any attached project documents for additional detail."
_NOTE = generator.ATTACHMENT_SENTENCE


def test_templates_never_mention_attachments():
    body = generator._sub_template_body("We are seeking bids.", "Install 40 LF of pipe.")
    assert "attach" not in body.lower()
    assert "Scope of work:" in body and "Your prompt response is appreciated." in body
    assert "attach" not in generator._template_body("Please quote.", "- Pipe — 10 LF").lower()


def test_old_drafts_with_the_hedge_send_clean_when_nothing_is_attached(project, monkeypatch):
    """Backstop for drafts generated before the sentence left the template."""
    client, headers, pid = project
    rfq = _draft_rfq(client, headers, pid)
    r = _save(client, headers, pid, {**rfq, "body": rfq["body"] + "\n\n" + _OLD_NOTE + " Thanks."}, [])
    assert r.status_code == 200, r.text
    recorder = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: recorder)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    for m in recorder.sent:
        assert "attached" not in m["body"].lower()
        assert "Thanks." in m["body"]  # only that sentence is removed
    # The stored RFQ reads what went out.
    assert r.json()["body"] == recorder.sent[0]["body"]
    assert "attached" not in client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()["body"].lower()


def test_attachment_note_is_added_at_send_and_persisted_when_a_document_is_attached(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload_doc(client, headers, pid)
    rfq = _draft_rfq(client, headers, pid)
    assert "attach" not in rfq["body"].lower()  # the draft the user reviews has no note
    r = _save(client, headers, pid, rfq, [doc_id])
    assert r.status_code == 200, r.text
    recorder = _Recorder()
    monkeypatch.setattr(rfq_sender, "get_sender", lambda *a, **k: recorder)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    sent_body = recorder.sent[0]["body"]
    assert all(m["body"] == sent_body for m in recorder.sent)
    assert sent_body.count(_NOTE) == 1
    # Placed right before the closing sentence.
    assert sent_body.index(_NOTE) < sent_body.index("Your prompt response is appreciated.")
    assert sent_body.endswith("additional information to complete your quote.")
    # Persisted: the stored RFQ (and so the thread) shows what went out.
    assert r.json()["body"] == sent_body
    assert client.get(f"/api/projects/{pid}/rfqs/{rfq['id']}", headers=headers).json()["body"] == sent_body


def test_body_with_attachment_note_placement_and_idempotence():
    with_close = "Hello.\n\nScope.\n\nYour prompt response is appreciated. Thanks."
    out = generator.body_with_attachment_note(with_close)
    assert out == "Hello.\n\nScope.\n\n" + _NOTE + " Your prompt response is appreciated. Thanks."
    assert generator.body_with_attachment_note(out) == out  # idempotent
    assert generator.body_with_attachment_note(with_close.replace("any", "")) == out
    no_close = "Hello.\n\nScope."
    assert generator.body_with_attachment_note(no_close) == no_close + "\n\n" + _NOTE
    # An old hedge is normalised to the single current sentence.
    old = "Hello.\n\n" + _OLD_NOTE + " Your prompt response is appreciated."
    assert generator.body_with_attachment_note(old) == "Hello.\n\n" + _NOTE + " Your prompt response is appreciated."
    assert generator.body_for_send(old, False) == "Hello.\n\nYour prompt response is appreciated."


def test_documents_report_their_file_size_for_the_attachment_picker(project, monkeypatch):
    """The RFQ modal shows per-file sizes and keeps the running total under the
    email cap client-side; a BOM with no file has no size."""
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload_doc(client, headers, pid)
    bom_id = make_confirmed_bom(client, headers, pid)
    docs = {d["id"]: d for d in client.get(f"/api/projects/{pid}/documents", headers=headers).json()}
    assert docs[doc_id]["fileSize"] == len(_MINI_PDF) and docs[doc_id]["fileMissing"] is False
    assert docs[bom_id]["fileSize"] is None and docs[bom_id]["hasFile"] is False
    one = client.get(f"/api/documents/{doc_id}", headers=headers).json()
    assert one["fileSize"] == len(_MINI_PDF)
