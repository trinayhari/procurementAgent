"""Public approval links (signed single-use tokens): GET previews the
decision, POST executes it. Owned by the approvals work. Mounted without
auth in main.py."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/approvals", tags=["approvals"])
