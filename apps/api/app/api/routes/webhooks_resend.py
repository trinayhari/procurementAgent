"""Resend Inbound webhook (public; signature-verified). Owned by the Resend
transport work. Mounted without auth in main.py."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/webhooks/resend", tags=["webhooks"])
