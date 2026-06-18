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

app = FastAPI(title=settings.app_name, version="0.1.0")

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
