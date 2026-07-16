import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    audit,
    auth,
    dashboard,
    documents,
    jobs,
    projects,
    quotes,
    rfqs,
    sourcing,
    suppliers,
    timeline,
)
from app.config import settings
from app.core.security import get_current_user
from app.db import SessionLocal, init_db
from app.repositories import documents as documents_repo
from app.repositories import jobs as jobs_repo

logger = logging.getLogger(__name__)

_DEFAULT_JWT_SECRET = "dev-insecure-change-me"


def _validate_production_config() -> None:
    """Fail fast on unsafe production configuration (before serving a request)."""
    if settings.env != "production":
        return
    if settings.jwt_secret == _DEFAULT_JWT_SECRET:
        raise RuntimeError(
            "Refusing to start: PROCUREAI_JWT_SECRET is still the insecure default. "
            "Set a strong secret (e.g. `openssl rand -hex 32`) in the environment."
        )
    if all(origin.startswith(("http://localhost", "http://127.0.0.1")) for origin in settings.cors_origins):
        logger.warning(
            "PROCUREAI_CORS_ORIGINS only allows localhost — the deployed frontend "
            "will be blocked by CORS. Set it to the production frontend URL."
        )


_validate_production_config()

app = FastAPI(title=settings.app_name, version="0.1.0")


@app.on_event("startup")
def _on_startup() -> None:
    # Ensure the tables exist and starter projects/documents are seeded so the
    # app works on a fresh checkout. Alembic still owns schema migrations.
    init_db()
    with SessionLocal() as db:
        # A background extraction that was in flight when the process last died
        # (e.g. OOM-killed on a large plan set) leaves its document stuck in
        # 'Processing'. Nothing can still be extracting at boot, so clear those.
        orphaned = documents_repo.fail_orphaned_processing(db)
        if orphaned:
            logger.warning("Reset %d orphaned 'Processing' document(s): %s", len(orphaned), orphaned)
        # Likewise, background jobs stuck 'running' from before the restart are
        # dead — fail them into the exception queue so they can be retried.
        dead_jobs = jobs_repo.fail_orphaned_running(db)
        if dead_jobs:
            logger.warning("Failed %d orphaned running job(s): %s", len(dead_jobs), dead_jobs)
        # Documents persist now, but pick up any files dropped into the upload
        # dir out-of-band so they stay previewable. Local-disk concept only.
        if settings.storage_backend != "s3":
            documents_repo.rehydrate_uploads(db, settings.upload_dir)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


# The auth router handles its own gating (login/register are public; /me routes
# depend on get_current_user themselves). documents.file_router serves signed
# file URLs validated by a scoped query token (iframes can't send headers).
app.include_router(auth.router)
app.include_router(documents.file_router)

# Every other route requires an authenticated user.
_authed = [Depends(get_current_user)]
for module in (dashboard, projects, sourcing, suppliers, documents, rfqs, quotes, timeline, jobs, audit):
    app.include_router(module.router, dependencies=_authed)
