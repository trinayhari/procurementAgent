from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    dashboard,
    documents,
    projects,
    quotes,
    rfqs,
    suppliers,
    timeline,
)
from app.config import settings
from app.db import init_db

app = FastAPI(title=settings.app_name, version="0.1.0")


@app.on_event("startup")
def _on_startup() -> None:
    # Ensure the projects table exists and starter projects are seeded so the app
    # works on a fresh checkout. Alembic still owns schema migrations.
    init_db()


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


for module in (dashboard, projects, suppliers, documents, rfqs, quotes, timeline):
    app.include_router(module.router)
