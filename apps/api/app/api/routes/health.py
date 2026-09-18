"""Provider health: does Gmail / the LLM actually answer right now?

`GET /api/auth/email-config` reports configuration and the *last observed*
outcome without touching the network. This endpoint makes real calls — a
send-scope token refresh, `users.getProfile` with the read scope, and a
one-token completion — so the founder can verify a freshly minted token or a
fixed API key from Settings. Authenticated, rate-limited, and never called on
page load (the Gmail token endpoint throttles refreshes).
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.ratelimit import rate_limit
from app.core.security import get_current_user
from app.models.user import User
from app.services import llm_health
from app.services.rfq import sender as rfq_sender

router = APIRouter(prefix="/api/health", tags=["health"])

_probe_limit = rate_limit("providers-probe", limit=3, window_s=60)


class ProviderProbe(BaseModel):
    ok: bool
    error: Optional[str] = None


class GmailProbe(ProviderProbe):
    emailAddress: Optional[str] = None  # the mailbox the token belongs to
    senderAddress: str  # PROCUREAI_GMAIL_SENDER_ADDRESS (or the placeholder)
    senderAddressMatches: Optional[bool] = None
    sendScope: bool = False  # the send-scope token refreshed
    readScope: bool = False  # the read-scope call succeeded


class LlmProbe(ProviderProbe):
    model: Optional[str] = None


class ProvidersHealth(BaseModel):
    ok: bool
    gmail: GmailProbe
    llm: LlmProbe


@router.get("/providers", response_model=ProvidersHealth, dependencies=[Depends(_probe_limit)])
def providers_health(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    gmail = rfq_sender.probe_gmail()
    llm = llm_health.probe()
    return {"ok": bool(gmail["ok"] and llm["ok"]), "gmail": gmail, "llm": llm}
