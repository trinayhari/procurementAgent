"""Object-storage abstraction: local + S3 backends, checksums, presign flow.

The S3 backend is exercised against an in-memory fake client (no boto3
network calls) injected via storage.set_s3_client().
"""
import io
import os

import pytest

from app.api.routes import documents as documents_routes
from app.config import settings
from app.services import storage
from tests.test_uploads import _MINI_PDF, _upload


class FakeS3Client:
    """Dict-backed stand-in for the small boto3 surface storage.py uses."""

    def __init__(self):
        self.objects = {}
        self.presigned = []

    def upload_fileobj(self, fh, bucket, key):
        self.objects[(bucket, key)] = fh.read()

    def download_file(self, bucket, key, dest):
        with open(dest, "wb") as fh:
            fh.write(self.objects[(bucket, key)])

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.presigned.append((op, Params, ExpiresIn))
        return f"https://fake-s3.example.com/{Params['Bucket']}/{Params['Key']}?sig=abc"


@pytest.fixture()
def s3(monkeypatch):
    fake = FakeS3Client()
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "test-bucket")
    monkeypatch.setattr(settings, "s3_prefix", "uploads")
    storage.set_s3_client(fake)
    yield fake
    storage.set_s3_client(None)


def test_upload_records_checksum(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    doc = _upload(client, headers, "plan.pdf").json()
    import hashlib

    assert doc["checksum"] == hashlib.sha256(_MINI_PDF).hexdigest()


def test_s3_upload_serve_delete_roundtrip(project, monkeypatch, s3):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)

    doc = _upload(client, headers, "site-plan.pdf").json()
    doc_id = doc["id"]

    # Stored in the fake bucket under the prefix, with the checksum recorded.
    assert len(s3.objects) == 1
    (bucket, key), body = next(iter(s3.objects.items()))
    assert bucket == "test-bucket" and key.startswith("uploads/") and key.endswith("_site-plan.pdf")
    assert body == _MINI_PDF

    # Signed URL flow → 307 redirect to a presigned URL (inline disposition).
    url = client.get(f"/api/documents/{doc_id}/file-url", headers=headers).json()["url"]
    r = client.get(url, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://fake-s3.example.com/test-bucket/")
    assert s3.presigned[-1][1]["ResponseContentDisposition"].startswith("inline")

    # local_copy materialises the object for extraction, then cleans up.
    from app.db import SessionLocal
    from app.repositories import documents as documents_repo

    with SessionLocal() as db:
        locator = documents_repo.get(db, doc_id).source_path
    assert locator == f"s3://test-bucket/{key}"
    with storage.local_copy(locator) as path:
        with open(path, "rb") as fh:
            assert fh.read() == _MINI_PDF
        tmp = path
    assert not os.path.exists(tmp)

    # Deleting the document removes the object from the bucket.
    assert client.delete(f"/api/documents/{doc_id}", headers=headers).status_code == 204
    assert s3.objects == {}


def test_local_files_still_work_when_backend_is_s3(project, monkeypatch, s3):
    """Files stored on disk before a switch to S3 keep serving (dispatch is
    per-locator, not global)."""
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    # Store one file locally first…
    monkeypatch.setattr(settings, "storage_backend", "local")
    doc_id = _upload(client, headers, "old-plan.pdf").json()["id"]
    # …then "switch" the deployment to S3.
    monkeypatch.setattr(settings, "storage_backend", "s3")
    url = client.get(f"/api/documents/{doc_id}/file-url", headers=headers).json()["url"]
    r = client.get(url)
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_upload_too_large_is_rejected(project, monkeypatch):
    client, headers, pid = project
    monkeypatch.setattr(documents_routes, "_run_pipeline", lambda *a, **k: None)
    monkeypatch.setattr(settings, "max_upload_mb", 0)  # cap = 0 bytes
    r = client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("big.pdf", io.BytesIO(_MINI_PDF), "application/pdf")},
        data={"project_id": pid, "plan_type": "other"},
    )
    assert r.status_code == 413
