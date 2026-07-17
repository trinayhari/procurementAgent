"""RFQ status state machine — the single place legal transitions are defined.

Statuses:
    Draft        — generated, editable, not yet sent
    Awaiting     — sent to every recipient, awaiting supplier quotes
    Send failed  — at least one recipient failed to send (retryable)
    Quoted       — one or more quotes ingested
    Sent         — legacy alias of Awaiting kept for pre-existing rows

Repositories call `assert_transition` before flipping a status, so an illegal
jump raises instead of silently corrupting workflow state.
"""
from typing import Optional

_ALLOWED = {
    ("Draft", "Awaiting"),
    ("Draft", "Send failed"),
    ("Send failed", "Awaiting"),
    # A partial failure still delivered to some suppliers — their quotes may
    # arrive before (or instead of) a successful retry.
    ("Send failed", "Quoted"),
    ("Sent", "Awaiting"),
    ("Sent", "Quoted"),
    ("Awaiting", "Quoted"),
}

# Statuses from which POST .../send is permitted.
SENDABLE = {"Draft", "Send failed"}

# Statuses in which the draft (subject/body/recipients) may still be edited.
EDITABLE = {"Draft"}


class IllegalTransition(ValueError):
    def __init__(self, current: str, new: str):
        self.current = current
        self.new = new
        super().__init__(f"Illegal RFQ status transition: {current!r} → {new!r}")


def assert_transition(current: Optional[str], new: str) -> None:
    """Raise IllegalTransition unless current → new is legal.

    Same-state transitions are allowed everywhere — repeated operations
    (a second ingest pass on a Quoted RFQ, a retry that fails again) are
    idempotent no-ops, not errors."""
    cur = current or "Draft"
    if cur == new:
        return
    if (cur, new) not in _ALLOWED:
        raise IllegalTransition(cur, new)


def recipient_sent(recipient: dict) -> bool:
    """True when this recipient already received the RFQ successfully.

    New sends record sendStatus="sent"; rows written before that field existed
    are recognised by a clean (non-"error:") sentMessageId."""
    if recipient.get("sendStatus") == "sent":
        return True
    if recipient.get("sendStatus") == "failed":
        return False
    message_id = str(recipient.get("sentMessageId") or "")
    return bool(message_id) and not message_id.startswith("error:")
