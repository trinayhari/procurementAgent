"""Document preview: server-rendered page images, signed access, caching.

The panel renders pages as images rather than embedding the original file, so
these cover the contract it relies on — a page count, one signed token good for
every page, real image bytes, and no way to read another document's pages.
"""
import io
import os

import pytest

from app.api.routes import documents as documents_routes
from app.services import preview

# A 1x1 PNG — enough to prove image uploads preview without rasterising.
_MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _pdf_bytes(pages: int = 3, tag: str = "Sheet") -> bytes:
    """A real multi-page PDF built with PyMuPDF (the renderer under test).

    `tag` varies the drawn text so two fixtures render to visibly different
    images — otherwise every page 1 rasterises to identical bytes.
    """
    fitz = pytest.importorskip("fitz", reason="PyMuPDF is required to render previews")
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 100), f"{tag} {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def _upload(client, headers, filename, content, mime="application/pdf", project_id="test-project"):
    # Upload validates project ownership, so project_id must be a project the
    # caller's org owns — "test-project" is what the conftest `project` fixture
    # creates (slug of "Test Project").
    return client.post(
        "/api/documents",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), mime)},
        data={"project_id": project_id, "plan_type": "other"},
    )


@pytest.fixture()
def uploaded(project, monkeypatch):
    """(client, headers, doc_id) for a 3-page PDF, extraction stubbed out."""
    client, headers, _pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload(client, headers, "plans.pdf", _pdf_bytes(3)).json()["id"]
    return client, headers, doc_id


def test_preview_reports_pages_and_renders_them(uploaded):
    client, headers, doc_id = uploaded
    r = client.get(f"/api/documents/{doc_id}/preview", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pages"] == 3
    assert "{page}" in body["pageUrl"]

    # Every page renders to a real PNG.
    for page in range(3):
        r = client.get(body["pageUrl"].replace("{page}", str(page)))
        assert r.status_code == 200
        assert r.content.startswith(b"\x89PNG"), f"page {page} is not a PNG"
        assert r.headers["content-type"] == "image/png"


def test_pages_beyond_the_document_are_not_found(uploaded):
    client, headers, doc_id = uploaded
    url = client.get(f"/api/documents/{doc_id}/preview", headers=headers).json()["pageUrl"]
    assert client.get(url.replace("{page}", "3")).status_code == 404
    assert client.get(url.replace("{page}", "-1")).status_code == 404


def test_pages_need_a_token_scoped_to_that_document(project, monkeypatch):
    client, headers, _pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload(client, headers, "a.pdf", _pdf_bytes(1)).json()["id"]
    other_id = _upload(client, headers, "b.pdf", _pdf_bytes(1)).json()["id"]

    # Unsigned access is refused.
    assert client.get(f"/api/documents/{doc_id}/page/0").status_code == 401
    assert client.get(f"/api/documents/{doc_id}/page/0?token=nonsense").status_code == 401

    # A valid token works only for the document it was minted for.
    url = client.get(f"/api/documents/{doc_id}/preview", headers=headers).json()["pageUrl"]
    token = url.split("token=")[1]
    assert client.get(url.replace("{page}", "0")).status_code == 200
    assert client.get(f"/api/documents/{other_id}/page/0?token={token}").status_code == 401


def test_a_page_is_only_rendered_once(uploaded, monkeypatch):
    """The second request for a page is served from the on-disk cache — rendering
    spawns a subprocess, so repeat views must not pay for it again."""
    client, headers, doc_id = uploaded
    url = client.get(f"/api/documents/{doc_id}/preview", headers=headers).json()["pageUrl"]
    assert client.get(url.replace("{page}", "0")).status_code == 200

    renders = []
    real = preview._render_isolated
    monkeypatch.setattr(
        preview, "_render_isolated",
        lambda *a, **k: (renders.append(a) or real(*a, **k)),
    )
    assert client.get(url.replace("{page}", "0")).status_code == 200
    assert renders == [], "cached page was re-rendered"
    # …but a page that hasn't been rendered yet still is.
    assert client.get(url.replace("{page}", "1")).status_code == 200
    assert len(renders) == 1


def test_page_count_is_probed_and_persisted_for_older_documents(uploaded):
    """Documents uploaded before the count was recorded still preview: the count
    is probed from the file and written back, so it's paid for once."""
    client, headers, doc_id = uploaded
    from app.db import SessionLocal
    from app.repositories import documents as documents_repo
    from app.repositories import users as users_repo

    with SessionLocal() as db:
        org_id = users_repo.get_by_email(db, "pm@example.com").organization_id
        documents_repo.update_status(db, org_id, doc_id, pages=0)

    assert client.get(f"/api/documents/{doc_id}/preview", headers=headers).json()["pages"] == 3
    with SessionLocal() as db:
        org_id = users_repo.get_by_email(db, "pm@example.com").organization_id
        assert documents_repo.get(db, org_id, doc_id).pages == 3


def test_image_uploads_preview_as_a_single_page(project, monkeypatch):
    client, headers, _pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload(client, headers, "scan.png", _MINI_PNG, "image/png").json()["id"]

    body = client.get(f"/api/documents/{doc_id}/preview", headers=headers).json()
    assert body["pages"] == 1
    r = client.get(body["pageUrl"].replace("{page}", "0"))
    assert r.status_code == 200
    assert r.content == _MINI_PNG  # served as-is; the browser scales it


def test_documents_without_a_file_have_no_preview(project):
    """A hand-built BOM has no source file — the panel shows the editor instead."""
    client, headers, pid = project
    r = client.post("/api/documents/manual", headers=headers, json={"name": "BOM", "projectId": pid})
    doc_id = r.json()["id"]
    assert client.get(f"/api/documents/{doc_id}/preview", headers=headers).status_code == 404


def test_a_corrupt_pdf_fails_the_page_not_the_api(project, monkeypatch):
    """A file that PyMuPDF can't parse must surface as an error response — the
    render runs in a child process precisely so it can't take the API down."""
    client, headers, _pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc_id = _upload(client, headers, "broken.pdf", b"%PDF-1.4 not really a pdf").json()["id"]

    body = client.get(f"/api/documents/{doc_id}/preview", headers=headers).json()
    if body["pages"]:  # unparseable files usually report 0 pages and offer the original
        assert client.get(body["pageUrl"].replace("{page}", "0")).status_code in (404, 502)
    # The API is still alive.
    assert client.get("/health").status_code == 200


def test_replacing_a_document_does_not_serve_the_old_pages(project, monkeypatch):
    """Cache keys are content checksums, so a re-upload never shows stale pages."""
    client, headers, _pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    first = _upload(client, headers, "plan.pdf", _pdf_bytes(2, tag="OLD")).json()["id"]
    second = _upload(client, headers, "plan.pdf", _pdf_bytes(5, tag="NEW")).json()["id"]

    a = client.get(f"/api/documents/{first}/preview", headers=headers).json()
    b = client.get(f"/api/documents/{second}/preview", headers=headers).json()
    assert (a["pages"], b["pages"]) == (2, 5)
    page_a = client.get(a["pageUrl"].replace("{page}", "0")).content
    page_b = client.get(b["pageUrl"].replace("{page}", "0")).content
    assert page_a != page_b
