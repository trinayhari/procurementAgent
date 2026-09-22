"""AgentMail webhook (public; Svix signature-verified). Owned by the AgentMail
transport work. Mounted without auth in main.py."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/webhooks/agentmail", tags=["webhooks"])
