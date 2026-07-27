"""Object-storage abstraction for uploaded documents.

Two backends behind one module-level API, selected by locator prefix so a
deployment can switch backends without breaking previously stored files:

- **local** (default): files under ``settings.upload_dir``; the locator is the
  filesystem path, exactly as before this module existed.
- **s3**: any S3-compatible store (AWS S3, Cloudflare R2, MinIO); the locator
  is ``s3://<bucket>/<key>``. Serving redirects to a presigned URL, and
  processing (PyMuPDF runs on a filesystem path) downloads to a temp file via
  :func:`local_copy`.

Uploads are streamed to a temp file first (size-capped, SHA-256 hashed), then
handed to the active backend — see :func:`save_upload`.
"""
import hashlib
import logging
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

from fastapi.responses import FileResponse, RedirectResponse, Response

from app.config import settings

logger = logging.getLogger("procureai.storage")

_CHUNK = 1024 * 1024


class UploadTooLarge(Exception):
    """Raised mid-stream when an upload exceeds the configured size cap."""


@dataclass
class StoredFile:
    locator: str  # backend-specific reference persisted on the document row
    sha256: str
    size: int


# --------------------------------------------------------------------- helpers
def _is_s3(locator: str) -> bool:
    return locator.startswith("s3://")


def _parse_s3(locator: str):
    rest = locator[len("s3://"):]
    bucket, _, key = rest.partition("/")
    return bucket, key


_s3_client = None


def _s3():
    """Lazily build (and cache) the boto3 client — only when the s3 backend or
    an s3 locator is actually used, so boto3 stays an optional dependency for
    local-only deployments."""
    global _s3_client
    if _s3_client is None:
        import boto3  # deferred import

        _s3_client = boto3.client(
            "s3",
            region_name=settings.s3_region or None,
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )
    return _s3_client


def set_s3_client(client) -> None:
    """Test hook: inject a fake S3 client."""
    global _s3_client
    _s3_client = client


def backend_name() -> str:
    return "s3" if settings.storage_backend == "s3" else "local"


# ---------------------------------------------------------------------- writes
async def stream_upload_to_temp(upload, max_bytes: int) -> StoredFile:
    """Drain a FastAPI UploadFile into a temp file, hashing as we go.

    Raises UploadTooLarge past the cap (temp file cleaned up). Returns a
    StoredFile whose locator is the TEMP path — pass it to persist_temp."""
    digest = hashlib.sha256()
    size = 0
    # Preserve the upload's extension: page_count/vision key off it, so an
    # extensionless temp path is read as an unsupported type (pages=0), which
    # would wrongly mark a valid PDF non-analyzable and skip the pipeline.
    suffix = os.path.splitext(os.path.basename(upload.filename or ""))[1].lower()
    fd, tmp_path = tempfile.mkstemp(prefix="procureai-upload-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            while True:
                chunk = await upload.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLarge()
                digest.update(chunk)
                fh.write(chunk)
    except Exception:
        os.unlink(tmp_path)
        raise
    return StoredFile(locator=tmp_path, sha256=digest.hexdigest(), size=size)


def persist_temp(temp: StoredFile, safe_name: str) -> StoredFile:
    """Move a drained temp file into the active backend under a unique name."""
    unique = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    if backend_name() == "s3":
        key = f"{settings.s3_prefix.strip('/')}/{unique}" if settings.s3_prefix else unique
        with open(temp.locator, "rb") as fh:
            _s3().upload_fileobj(fh, settings.s3_bucket, key)
        os.unlink(temp.locator)
        locator = f"s3://{settings.s3_bucket}/{key}"
    else:
        os.makedirs(settings.upload_dir, exist_ok=True)
        dest = os.path.join(settings.upload_dir, unique)
        shutil.move(temp.locator, dest)
        locator = dest
    return StoredFile(locator=locator, sha256=temp.sha256, size=temp.size)


# ----------------------------------------------------------------------- reads
def exists(locator: Optional[str]) -> bool:
    if not locator:
        return False
    if _is_s3(locator):
        bucket, key = _parse_s3(locator)
        try:
            _s3().head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False
    return os.path.exists(locator)


@contextmanager
def local_copy(locator: str) -> Iterator[str]:
    """Yield a local filesystem path for `locator` (extraction needs a path).

    Local backend: the path itself (no copy). S3: downloads to a temp file
    that is removed afterwards."""
    if not _is_s3(locator):
        yield locator
        return
    bucket, key = _parse_s3(locator)
    suffix = os.path.splitext(key)[1]
    fd, tmp_path = tempfile.mkstemp(prefix="procureai-s3-", suffix=suffix)
    os.close(fd)
    try:
        _s3().download_file(bucket, key, tmp_path)
        yield tmp_path
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def serve(locator: str, display_name: str) -> Response:
    """Response serving the file inline: FileResponse locally, a redirect to a
    short-lived presigned URL for S3."""
    ext = os.path.splitext(locator)[1].lower()
    media_type = "application/pdf" if ext == ".pdf" else "application/octet-stream"
    if _is_s3(locator):
        bucket, key = _parse_s3(locator)
        url = _s3().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ResponseContentType": media_type,
                "ResponseContentDisposition": f'inline; filename="{display_name}"',
            },
            ExpiresIn=settings.s3_presign_expiry_s,
        )
        return RedirectResponse(url, status_code=307)
    return FileResponse(
        locator,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{display_name}"'},
    )


def delete(locator: Optional[str]) -> None:
    """Best-effort removal of the stored file (never raises)."""
    if not locator:
        return
    try:
        if _is_s3(locator):
            bucket, key = _parse_s3(locator)
            _s3().delete_object(Bucket=bucket, Key=key)
        elif os.path.exists(locator):
            os.remove(locator)
    except Exception:
        logger.warning("Could not delete stored file %s", locator, exc_info=True)
