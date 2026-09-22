"""Outbound notices: how the agent talks back to the customer.

Proq is meant to feel like a coworker on the procurement desk: the customer
sends requirements by email or Slack and the agent reports progress back to
wherever the conversation started, with an action button when a human call
is needed (approve an award, confirm a BOM). This package is the one seam
every channel plugs into.

    from app.services import notify

    notify.emit(db, notify.Notice(
        org_id=org_id, project_id=project_id, kind="award.ready",
        title="Riverside WTP: water utilities award ready",
        lines=["Quotes leveled to the line: 5 of 7 suppliers",
               "Freight and lead time priced in: 14d / 16d"],
        actions=[notify.Action("Approve award", url=approve_url, style="primary"),
                 notify.Action("See the comparison", url=compare_url)],
    ))

`emit` fans the notice out to every registered Notifier (email, Slack, the
in-app activity feed). Channels are registered at import time by their own
modules; nothing here knows about a transport. A notifier that raises must
not break the caller: emit logs and moves on.

Thread continuity: a Notice may carry a `thread` (where the conversation
started) so a channel can reply in place, e.g. the email thread the plan set
arrived in, or the Slack channel + ts of the intake message.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

logger = logging.getLogger("procureai.notify")


@dataclass(frozen=True)
class Action:
    """A button on the notice. `url` is a public link (approval token page);
    a channel with native buttons (Slack) may render it as one and post the
    result back through the same url."""

    label: str
    url: str
    style: str = "default"  # "primary" | "default"


@dataclass(frozen=True)
class ThreadRef:
    """Where the originating conversation lives, so a channel can reply in
    place. Exactly one of the channel-specific fields is set per ref."""

    channel: str  # "email" | "slack"
    # email: the RFC 2822 Message-ID of the message we are replying to, and
    # the address of the person who sent it.
    email_message_id: str = ""
    email_address: str = ""
    email_subject: str = ""
    # slack: the workspace channel and, when replying in a thread, the parent ts.
    slack_channel_id: str = ""
    slack_thread_ts: str = ""


@dataclass
class Notice:
    org_id: str
    kind: str  # dotted event name: "intake.received", "bom.drafted", "rfq.sent", "quotes.received", "award.ready", "award.approved", "po.issued", "followup.sent"
    title: str
    project_id: Optional[str] = None
    lines: List[str] = field(default_factory=list)
    actions: List[Action] = field(default_factory=list)
    thread: Optional[ThreadRef] = None
    # Free-form extras a channel may use (e.g. package key, amounts).
    meta: dict = field(default_factory=dict)


class Notifier(Protocol):
    name: str

    def notify(self, db, notice: Notice) -> None:
        """Deliver one notice. Raise to report failure; emit() isolates it."""
        ...


_NOTIFIERS: List[Notifier] = []


def register(notifier: Notifier) -> None:
    """Add a channel. Idempotent per notifier name so re-imports are safe."""
    for i, existing in enumerate(_NOTIFIERS):
        if getattr(existing, "name", None) == getattr(notifier, "name", None):
            _NOTIFIERS[i] = notifier
            return
    _NOTIFIERS.append(notifier)


def registered() -> List[str]:
    return [n.name for n in _NOTIFIERS]


def reset() -> None:
    """Tests only."""
    _NOTIFIERS.clear()


def emit(db, notice: Notice) -> None:
    """Fan a notice out to every channel. Never raises into the caller."""
    for notifier in list(_NOTIFIERS):
        try:
            notifier.notify(db, notice)
        except Exception:  # noqa: BLE001 - a dead channel must not break the flow
            logger.exception("notifier %s failed for %s", notifier.name, notice.kind)
