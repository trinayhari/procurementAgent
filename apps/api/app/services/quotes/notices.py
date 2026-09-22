"""The quotes.received notice and the award-readiness check that follows it.

Both the dashboard's "Check for replies" job (api/routes/sourcing.py) and the
webhook path for one supplier reply (services/inbound/rfq_replies.py) end
here, so the customer hears about new quotes, and gets the award card, no
matter which way the reply came in.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.repositories import projects as projects_repo
from app.repositories import quotes as quotes_repo
from app.repositories import rfqs as rfqs_repo
from app.services import notify
from app.services.notify import kinds as notice_kinds
from app.services.rfq import readiness
from app.services.rfq import state as rfq_state

logger = logging.getLogger("procureai.quotes.notices")


def notify_quotes_received(
    db: Session, org_id: str, project_id: str, *, packages: Optional[Iterable[str]] = None
) -> None:
    """One quotes.received notice per package that has quotes (every package,
    or only `packages`), then check whether each is ready to award (readiness
    mints the approval link and emits award.ready itself, once per quote set)."""
    only = {p for p in (packages or ()) if p} or None
    project = projects_repo.get_project(db, org_id, project_id) or {}
    project_name = project.get("name") or "Project"
    by_package: dict = {}
    for q in quotes_repo.list_quotes(db, org_id, project_id):
        if only is None or q["package"] in only:
            by_package.setdefault(q["package"], []).append(q)
    sent: dict = {}
    for rfq in rfqs_repo.list_awaiting_rfqs(db, org_id, project_id):
        for r in rfq.get("recipients", []):
            if rfq_state.recipient_sent(r) and r.get("email"):
                sent.setdefault(rfq["package"], set()).add(r["email"].strip().lower())
    for package, quotes in by_package.items():
        label = quotes[0].get("packageLabel") or package
        n_quoted = len({(q.get("supplierEmail") or q.get("supplierId") or q["id"]) for q in quotes})
        n_sent = max(len(sent.get(package, ())), n_quoted)
        notify.emit(db, notify.Notice(
            org_id=org_id, project_id=project_id, kind=notice_kinds.QUOTES_RECEIVED,
            title=f"{project_name}: {n_quoted} of {n_sent} suppliers replied for {label}",
            lines=[f"{n_quoted} quote{'s' if n_quoted != 1 else ''} leveled to the line"],
            meta={"package": package, "quoted": n_quoted, "sent": n_sent},
        ))
        try:
            readiness.announce(db, org_id, project_id, package)
        except Exception:  # noqa: BLE001 - the quote itself is already stored
            logger.exception("award readiness check failed for %s/%s", project_id, package)
