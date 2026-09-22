"""Provider health: does AgentMail / the LLM actually answer right now?

`GET /api/auth/email-config` reports configuration and the *last observed*
outcome without touching the network. This endpoint makes real calls: it
creates the organization's agent inbox if needed and reads it back, and runs
a one-token completion, so the founder can verify a fresh API key from
Settings. Authenticated, rate-limited, and never called on page load.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.ratelimit import rate_limit
from app.core.security import get_current_user
from app.db import get_db
from app.models.user import User
from app.services import llm_health
from app.services.rfq import sender as rfq_sender

router = APIRouter(prefix="/api/health", tags=["health"])

_probe_limit = rate_limit("providers-probe", limit=3, window_s=60)


class ProviderProbe(BaseModel):
    ok: bool
    error: Optional[str] = None


class EmailProbe(ProviderProbe):
    inboxAddress: Optional[str] = None  # the org's agent inbox, once it exists


class LlmProbe(ProviderProbe):
    model: Optional[str] = None


class ProvidersHealth(BaseModel):
    ok: bool
    email: EmailProbe
    llm: LlmProbe


@router.get("/providers", response_model=ProvidersHealth, dependencies=[Depends(_probe_limit)])
def providers_health(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    email = rfq_sender.probe_email(db, current_user.organization_id)
    llm = llm_health.probe()
    return {"ok": bool(email["ok"] and llm["ok"]), "email": email, "llm": llm}
