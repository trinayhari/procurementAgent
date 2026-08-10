"""User-selected document attachments on outgoing RFQ emails.

Attachment ids are validated at save (org/project ownership, has_file, size
budget) and hydrated into real bytes at send. A document deleted after save is
skipped, not fatal. The attachment-free path stays plain MIMEText.
"""
import io
from email import message_from_bytes
import base64

import pytest

from app.api.routes import documents as documents_routes
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
        self.sent.append({"to": to, "attachments": attachments})
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
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: recorder)
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
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: recorder)
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
    assert "15 MB" in r.json()["detail"]


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
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: recorder)
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
    monkeypatch.setattr(rfq_sender, "get_sender", lambda: recorder)
    r = client.post(f"/api/projects/{pid}/rfqs/{rfq['id']}/send", headers=headers)
    assert r.status_code == 200, r.text  # send still goes out
    assert all(m["attachments"] is None for m in recorder.sent)


# ------------------------------------------------------------- MIME building
def _decode_raw(raw: str):
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def test_build_mime_without_attachments_is_plain_text():
    raw = rfq_sender._build_mime("a@b.com", "Subj", "Body", "us@ours.com")
    msg = _decode_raw(raw)
    assert not msg.is_multipart()
    assert msg.get_payload() == "Body"


def test_build_mime_with_attachments_is_multipart():
    att = rfq_sender.EmailAttachment(filename="plan.pdf", content=_MINI_PDF)
    raw = rfq_sender._build_mime(
        "a@b.com", "Subj", "Body", "us@ours.com", attachments=[att]
    )
    msg = _decode_raw(raw)
    assert msg.is_multipart()
    body_part, att_part = msg.get_payload()
    assert body_part.get_payload() == "Body"
    assert att_part.get_filename() == "plan.pdf"
    assert att_part.get_content_type() == "application/pdf"
    assert att_part.get_payload(decode=True) == _MINI_PDF
    # The no-Reply-To invariant holds for multipart messages too.
    assert msg["Reply-To"] is None


def test_build_mime_unknown_extension_falls_back_to_octet_stream():
    att = rfq_sender.EmailAttachment(filename="takeoff.zz9", content=b"\x00\x01\x02")
    raw = rfq_sender._build_mime(
        "a@b.com", "Subj", "Body", "us@ours.com", attachments=[att]
    )
    msg = _decode_raw(raw)
    _, att_part = msg.get_payload()
    assert att_part.get_content_type() == "application/octet-stream"
    assert att_part.get_filename() == "takeoff.zz9"
    assert att_part.get_payload(decode=True) == b"\x00\x01\x02"
