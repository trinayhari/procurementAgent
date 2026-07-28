"""Progress emails to a project's lenders (PRO-16).

When the user checks a milestone off, every lender on the project gets a short
update: what was completed, how far along the schedule is, and what's next.
Runs as a FastAPI background task (its own DB session) so a slow Gmail call
never delays the check-off response; failures are logged, never raised.
"""
import logging

from typing import Optional

from app.db import SessionLocal
from app.repositories import events as events_repo
from app.repositories import lenders as lenders_repo
from app.repositories import projects as projects_repo
from app.repositories import timeline as timeline_repo
from app.repositories import users as users_repo
from app.services import schedule as schedule_service
from app.services.rfq import sender as rfq_sender

logger = logging.getLogger("procureai.lender_updates")


def _compose(project: dict, milestone_name: str, milestones: list) -> tuple:
    """Subject + body for one completed milestone, with schedule context."""
    done = sum(1 for m in milestones if m["done"])
    total = len(milestones)
    nxt = next((m for m in milestones if not m["done"]), None)
    loc = f" ({project['loc']})" if project.get("loc") and project["loc"] != "—" else ""

    progress = f" ({done} of {total} milestones)" if total else ""
    subject = f"{project['name']} — Milestone complete: {milestone_name}{progress}"
    lines = [
        f"Progress update for {project['name']}{loc}:",
        "",
        f'The milestone "{milestone_name}" has been completed.',
        f"Schedule progress: {done} of {total} milestones complete.",
    ]
    if nxt:
        when = f" — {nxt['date']}" if nxt.get("date") and nxt["date"] != "—" else ""
        lines.append(f"Next up: {nxt['name']}{when}.")
    else:
        lines.append("All scheduled milestones are now complete.")
    lines += [
        "",
        "You're receiving this because you're listed as a lender contact on this project.",
        "",
        "— Proq",
    ]
    return subject, "\n".join(lines)


def send_milestone_update(
    project_id: str, milestone_name: str, actor_user_id: Optional[str] = None
) -> None:
    """Email every lender on the project that `milestone_name` was completed.

    `actor_user_id` is the user who checked the milestone off: their name/company
    become the From display name and their Cc address gets a copy. The From
    mailbox itself is always the workspace account (see services/rfq/sender.py).

    Background-task entrypoint: opens its own session, swallows all errors."""
    try:
        with SessionLocal() as db:
            lenders = lenders_repo.list_for_project(db, project_id)
            if not lenders:
                return
            project = projects_repo.get_project(db, project_id)
            if project is None:
                return
            built = schedule_service.build_schedule(
                timeline_repo.list_for_project(db, project_id)
            )
            milestones = built["milestones"] if built else []
            subject, body = _compose(project, milestone_name, milestones)

            sender = rfq_sender.get_sender()
            actor = users_repo.get_user(db, actor_user_id) if actor_user_id else None
            from_addr = rfq_sender.from_header(actor)
            cc = getattr(actor, "cc_email", None)
            delivered = 0
            for lender in lenders:
                try:
                    sender.send(lender["email"], subject, body, from_addr=from_addr, cc=cc)
                    delivered += 1
                except Exception:
                    logger.exception(
                        "Lender update failed: project=%s to=%s", project_id, lender["email"]
                    )
            if delivered:
                events_repo.log(
                    db,
                    project_id,
                    title=f"Progress update emailed to {delivered} lender{'s' if delivered != 1 else ''}",
                    icon="rfq",
                    tone="success",
                    meta=f"{milestone_name} complete"
                    + (" (mock send — Gmail not configured)" if sender.mocked else ""),
                )
    except Exception:  # never let a notification failure surface anywhere
        logger.exception("Lender update crashed: project=%s", project_id)
