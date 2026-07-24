"""Upload safety: extension allowlist, collision-proof storage, signed URLs."""
import io
import os

from app.api.routes import documents as documents_routes
from app.config import settings

# A tiny valid one-page PDF.
_MINI_PDF = (
    b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
)


def _upload(client, headers, filename, content=_MINI_PDF):
    return client.post(
        "/api/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
        data={"project_id": "does-not-matter", "plan_type": "other"},
    )


def test_rejects_disallowed_extensions(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    r = client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        data={"project_id": pid},
    )
    assert r.status_code == 400
    assert "Unsupported file type" in r.json()["detail"]


def test_same_named_uploads_do_not_collide(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    r1 = _upload(client, headers, "plan.pdf")
    r2 = _upload(client, headers, "plan.pdf")
    assert r1.status_code == 201 and r2.status_code == 201

    from app.db import SessionLocal
    from app.repositories import documents as documents_repo

    with SessionLocal() as db:
        d1 = documents_repo.get(db, r1.json()["id"])
        d2 = documents_repo.get(db, r2.json()["id"])
        assert d1.source_path != d2.source_path
        assert os.path.exists(d1.source_path) and os.path.exists(d2.source_path)
        # Display names keep the original filename.
        assert d1.name == d2.name == "plan"


def test_signed_file_url_flow(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload(client, headers, "site-plan.pdf").json()["id"]

    # Direct access without a token is refused.
    assert client.get(f"/api/documents/{doc_id}/file").status_code == 401

    # The signed URL works.
    r = client.get(f"/api/documents/{doc_id}/file-url", headers=headers)
    assert r.status_code == 200
    url = r.json()["url"]
    r = client.get(url)
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")

    # …but only for its own document.
    other_id = _upload(client, headers, "other.pdf").json()["id"]
    token = url.split("token=")[1]
    assert client.get(f"/api/documents/{other_id}/file?token={token}").status_code == 401


def test_uploads_stored_under_upload_dir(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload(client, headers, "plan.pdf").json()["id"]
    from app.db import SessionLocal
    from app.repositories import documents as documents_repo

    with SessionLocal() as db:
        doc = documents_repo.get(db, doc_id)
        assert os.path.dirname(os.path.abspath(doc.source_path)) == os.path.abspath(
            settings.upload_dir
        )
