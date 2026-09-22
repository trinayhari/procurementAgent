import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health as health_routes
from app.api.routes import (
    approvals,
    audit,
    auth,
    bench,
    dashboard,
    documents,
    inbound,
    intake,
    jobs,
    projects,
    quotes,
    rfqs,
    slack,
    sourcing,
    suppliers,
    team,
    timeline,
    webhooks_agentmail,
    webhooks_slack,
)
from app.config import settings
from app.core.security import get_current_user
from app.db import DEMO_ORG_ID, SessionLocal, init_db
from app.repositories import documents as documents_repo
from app.repositories import jobs as jobs_repo
from app.services import scheduler
from app.services.notify import setup as notify_setup
from app.services.rfq import followups as _followups  # noqa: F401 - registers its scheduler job

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
        # Gated on demo seeding: an out-of-band file has no discoverable owner,
        # and guessing an organization for it would put one tenant's file in
        # another's document list. In a demo environment the demo org (which
        # owns the `riverside` project these attach to) is the right home.
        if settings.storage_backend != "s3" and settings.seed_demo_data:
            documents_repo.rehydrate_uploads(db, settings.upload_dir, DEMO_ORG_ID)
    notify_setup.install()  # email, activity-feed and Slack channels for services.notify
    # Periodic work (supplier follow-ups etc.); durable state is in the DB.
    scheduler.start()


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
# Public invite preview/accept: the invitee has no account yet, so these gate
# on a secret token, not a bearer session.
app.include_router(team.public_router)
# Inbound webhooks verify their provider's signature instead of a session, and
# approval links gate on a signed single-use token (the approver may have no
# account: the award card lands in email or Slack).
app.include_router(webhooks_agentmail.router)
app.include_router(webhooks_slack.router)
app.include_router(approvals.router)

# Every other route requires an authenticated user.
_authed = [Depends(get_current_user)]
for module in (dashboard, projects, sourcing, suppliers, documents, intake, inbound, rfqs, quotes, timeline, jobs, audit, team, slack, health_routes):
    app.include_router(module.router, dependencies=_authed)

# The eval bench (docs/eval-harness.md) is a local tuning tool: unauthenticated,
# and mounted only outside production. Production hard-refuses it regardless of
# the flag, so a stray PROCUREAI_BENCH_ENABLED can't expose the corpus.
if settings.bench_enabled and settings.env != "production":
    app.include_router(bench.router)
elif settings.bench_enabled:
    logger.warning("PROCUREAI_BENCH_ENABLED is set but env=production — bench routes NOT mounted.")
