import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    auth,
    dashboard,
    documents,
    projects,
    quotes,
    rfqs,
    sourcing,
    suppliers,
    timeline,
)
from app.config import settings
from app.db import SessionLocal, init_db
from app.repositories import documents as documents_repo

app = FastAPI(title=settings.app_name, version="0.1.0")
logger = logging.getLogger(__name__)


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
        # Documents persist now, but pick up any files dropped into the upload
        # dir out-of-band so they stay previewable.
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


for module in (auth, dashboard, projects, sourcing, suppliers, documents, rfqs, quotes, timeline):
    app.include_router(module.router)
