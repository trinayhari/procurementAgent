"""RFQ generation + sending.

``generator`` builds a per-package RFQ draft (gpt-4.1 body when configured, else a
deterministic template). ``sender`` delivers it via Gmail, behind an interface
with a mock that only logs — so drafts can be "sent" offline.
"""
from app.services.rfq import generator, sender

__all__ = ["generator", "sender"]
