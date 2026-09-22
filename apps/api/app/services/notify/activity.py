"""In-app channel: every notice also lands in the project's activity feed, so
the dashboard shows the same stream the customer sees in email or Slack.
Notices without a project (none today) have no feed to land in and are skipped.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories import events as events_repo
from app.services.notify import Notice
from app.services.notify import kinds

# (icon, tone) per kind; names match the web ICONS map and event tones.
_STYLE = {
    kinds.INTAKE_RECEIVED: ("file", "blue"),
    kinds.INTAKE_NOTED: ("file", "blue"),
    kinds.BOM_DRAFTED: ("sparkles", "ai"),
    kinds.RFQ_SENT: ("rfq", "success"),
    kinds.QUOTES_RECEIVED: ("quote", "violet"),
    kinds.AWARD_READY: ("check", "ai"),
    kinds.AWARD_APPROVED: ("check", "success"),
    kinds.PO_ISSUED: ("truck", "success"),
    kinds.FOLLOWUP_SENT: ("clock", "blue"),
}
_DEFAULT_STYLE = ("file", "blue")


class ActivityNotifier:
    name = "activity"

    def notify(self, db: Session, notice: Notice) -> None:
        if not notice.project_id:
            return
        icon, tone = _STYLE.get(notice.kind, _DEFAULT_STYLE)
        events_repo.log(
            db, notice.org_id, notice.project_id,
            title=notice.title, icon=icon, tone=tone,
            meta=" · ".join(notice.lines)[:200],
        )
