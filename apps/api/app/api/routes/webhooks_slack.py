"""Slack Events API + interactivity endpoints (public; signature-verified).
Owned by the Slack work. Mounted without auth in main.py."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/webhooks/slack", tags=["webhooks"])
