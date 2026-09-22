"""Autonomous supplier follow-ups: chase RFQ recipients who have not replied.

The agent's coworker move after an RFQ goes out. On a policy (the `followup_*`
settings), every recipient that received the RFQ and has not answered gets a
short nudge in the original email thread: the first after
`followup_first_delay_hours`, the second after `followup_second_delay_hours`,
never more than `followup_max`, and only inside the allowed local hours and
weekdays. Nobody clicks anything.

State is durable and lives on the recipient dict in `Rfq.recipients` JSON, so
a restart only delays a nudge by one poll interval and never repeats one:

    recipient["followups"] = [{"n": 1, "sentAt": iso, "messageId": str | None}, ...]

A nudge is written as an intent (no messageId) BEFORE the email goes out and
completed after. A crash between the two leaves an intent with no messageId;
one younger than INTENT_TIMEOUT is treated as in flight, an older one as a
failed send that may be retried. Either way the recipient is never chased
twice for the same nudge number.

A recipient counts as replied when `repliedAt` is set on the dict (the inbound
path writes it) or a Quote row exists for the RFQ and their address, so a
quote parsed before `repliedAt` existed still stops the chase.

Time: `run_due(now=...)` takes an aware datetime (defaults to utcnow) and a
`tz` (defaults to the server's local zone) so the send-window check is
deterministic under test.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import locks
from app.db import SessionLocal
from app.models.audit_event import AuditEvent
from app.models.quote import Quote
from app.models.rfq import Rfq
from app.repositories import audit as audit_repo
from app.repositories import purchase_decisions as decisions_repo
from app.repositories import rfqs as rfqs_repo
from app.repositories import users as users_repo
from app.services import llm_health, notify, scheduler
from app.services.rfq import sender as rfq_sender
from app.services.rfq import state as rfq_state

logger = logging.getLogger("procureai.rfq.followups")

# Stream C owns the notice-kind constants (services/notify/kinds.py:
# FOLLOWUP_SENT). Literal here so this module merges without that file.
FOLLOWUP_SENT = "followup.sent"
AUDIT_ACTION = "rfq.followup_sent"

# An intent (followup entry with no messageId) older than this is a send that
# died mid-flight and may be retried; younger ones are still in progress.
INTENT_TIMEOUT = timedelta(minutes=10)

# Statuses under which some recipient may already have received the RFQ.
# Mirrors rfqs_repo.list_awaiting_rfqs: eligibility is per recipient anyway
# (send succeeded, not replied), so a partially failed or already-Quoted RFQ
# still chases the suppliers who are outstanding.
_SENT_STATUSES = ("Sent", "Awaiting", "Quoted", "Send failed")


@dataclass
class FollowupRunSummary:
    rfqs_scanned: int = 0
    nudges_sent: int = 0
    skipped_outside_hours: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rfqsScanned": self.rfqs_scanned,
            "nudgesSent": self.nudges_sent,
            "skippedOutsideHours": self.skipped_outside_hours,
            "errors": list(self.errors),
        }


# ------------------------------------------------------------------- time
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Naive datetimes are UTC (how Rfq.sent_at round-trips through SQLite)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    try:
        return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


def within_send_window(now: datetime, tz=None) -> bool:
    """True when `now` falls inside the allowed local hours (and weekdays)."""
    local = _aware(now).astimezone(tz or _local_tz())
    if settings.followup_weekdays_only and local.weekday() >= 5:
        return False
    return settings.followup_send_hour_start <= local.hour < settings.followup_send_hour_end


# -------------------------------------------------------------- recipients
def _email(recipient: dict) -> str:
    return (recipient.get("email") or "").strip().lower()


def recipient_sent_at(rfq: dict, recipient: dict) -> Optional[datetime]:
    """When this recipient got the RFQ: their own `sentAt` (stream A writes
    it per send), else the RFQ's send time."""
    return _parse_iso(recipient.get("sentAt")) or _parse_iso(rfq.get("sentAt"))


def _has_quote(db: Session, org_id: str, rfq_id: str, recipient: dict) -> bool:
    email = _email(recipient)
    sid = recipient.get("supplierId")
    stmt = select(Quote.id).where(Quote.organization_id == org_id, Quote.rfq_id == rfq_id)
    if email and sid:
        stmt = stmt.where((func.lower(Quote.supplier_email) == email) | (Quote.supplier_id == sid))
    elif email:
        stmt = stmt.where(func.lower(Quote.supplier_email) == email)
    elif sid:
        stmt = stmt.where(Quote.supplier_id == sid)
    else:
        return False
    return db.scalars(stmt).first() is not None


def has_replied(db: Session, org_id: str, rfq_id: str, recipient: dict) -> bool:
    """Either reply signal: `repliedAt` on the dict, or a Quote row for the RFQ
    and this supplier (by address, or by supplier id when the estimator
    answered from a different mailbox)."""
    if recipient.get("repliedAt"):
        return True
    return _has_quote(db, org_id, rfq_id, recipient)


def _completed(recipient: dict) -> List[dict]:
    return [f for f in (recipient.get("followups") or []) if f.get("messageId")]


def _pending_intent(recipient: dict, now: datetime) -> Optional[dict]:
    """An intent still inside INTENT_TIMEOUT: another worker is mid-send."""
    for f in recipient.get("followups") or []:
        if f.get("messageId"):
            continue
        at = _parse_iso(f.get("sentAt"))
        if at is not None and now - at < INTENT_TIMEOUT:
            return f
    return None


def _delay_hours(n: int) -> Optional[int]:
    if n == 1:
        return settings.followup_first_delay_hours
    if n == 2:
        return settings.followup_second_delay_hours
    # Beyond the two configured delays: keep the second spacing.
    return settings.followup_second_delay_hours * (n - 1)


def next_nudge(rfq: dict, recipient: dict) -> Tuple[Optional[int], Optional[datetime]]:
    """(n, due_at) of the next nudge this recipient could get, or (None, None)
    when they are exhausted, never received the RFQ, or have no send time.
    Ignores replies and the send window: callers layer those on."""
    if not rfq_state.recipient_sent(recipient):
        return None, None
    sent_at = recipient_sent_at(rfq, recipient)
    if sent_at is None:
        return None, None
    completed = _completed(recipient)
    n = len(completed) + 1
    if n > settings.followup_max:
        return None, None
    delay = _delay_hours(n)
    if delay is None:
        return None, None
    due = sent_at + timedelta(hours=delay)
    if completed:
        # A late first nudge (scheduler down, weekend) must not be chased by
        # the second minutes later: keep the configured spacing between them.
        prev = _parse_iso(completed[-1].get("sentAt"))
        gap = delay - (_delay_hours(n - 1) or 0)
        if prev is not None and gap > 0:
            due = max(due, prev + timedelta(hours=gap))
    return n, due


# -------------------------------------------------------------------- draft
def _package_name(rfq: dict) -> str:
    return (rfq.get("pkg") or rfq.get("package") or "this package").strip()


def _need_by_line(rfq: dict) -> str:
    need_by = (rfq.get("needBy") or "").strip()
    return f"We need the material on site by {need_by}." if need_by else ""


def _signature(buyer) -> str:
    """"Jane Doe, Acme Construction" from the user who sent the RFQ."""
    name = (getattr(buyer, "name", "") or "").strip()
    company = (getattr(buyer, "company", "") or "").strip()
    return ", ".join(part for part in (name, company) if part)


def _template_body(rfq: dict, recipient: dict, n: int, outstanding: str, buyer) -> str:
    package = _package_name(rfq)
    greeting = "Hello,"
    if outstanding == "lead_time":
        ask = (
            f"Thank you for your quote on the {package} package. We still need "
            "your lead time to complete our comparison."
        )
        close = "Please reply to this email with your lead time and delivery date."
    else:
        when = "last week" if n > 1 else "recently"
        again = "again " if n > 1 else ""
        ask = (
            f"Following up {again}on the request for quote we sent {when} for the "
            f"{package} package. We have not received your quote yet and would "
            "like to include you in our comparison."
        )
        close = "Please reply to this email with your pricing and lead time."
    need_by = _need_by_line(rfq)
    signature = _signature(buyer)
    parts = [greeting, ask + (" " + need_by if need_by else ""), close, "Thanks,\n" + (signature or "Proq")]
    return "\n\n".join(parts)


def _llm_body(template: str, rfq: dict, n: int, outstanding: str) -> Optional[str]:
    """Reword the template with the RFQ generator's model when a key is set.
    Same client and health bookkeeping as services/rfq/generator.py."""
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)
        what = "their lead time" if outstanding == "lead_time" else "their quote"
        prompt = (
            f"Rewrite this supplier follow-up email (nudge {n} of {settings.followup_max}) "
            f"for the '{_package_name(rfq)}' package. Keep it short, polite and specific: "
            f"say what is outstanding ({what}), keep any need-by date exactly as written, "
            "and end with one line asking them to reply to this email with their pricing. "
            "Keep the greeting and signature as they are. No subject line, no em dashes.\n\n"
            f"{template}"
        )
        resp = client.chat.completions.create(
            model=settings.openai_vision_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300,
        )
        llm_health.record_success()
        text = (resp.choices[0].message.content or "").strip()
        return text.replace(chr(0x2014), ":") or None
    except Exception as exc:
        llm_health.record_failure(exc, "RFQ follow-up generator")
        return None


def draft_followup(
    rfq: dict, recipient: dict, n: int, *, outstanding: str = "quote", buyer=None
) -> Tuple[str, str]:
    """(subject, body) for nudge `n`. Subject replies in the RFQ thread.

    `outstanding` is "quote" (no answer at all) or "lead_time" (they quoted
    without one). Never raises: the model path falls back to the template."""
    subject = f"Re: {(rfq.get('subject') or '').strip()}"
    template = _template_body(rfq, recipient, n, outstanding, buyer)
    return subject, (_llm_body(template, rfq, n, outstanding) or template)


# ---------------------------------------------------------------- sending
def _rfq_sender_user(db: Session, org_id: str, rfq_id: str):
    """The user who sent the RFQ (from the rfq.sent audit entry) so the nudge
    is Cc'd to them, exactly as the original send was. None when unknown."""
    actor_id = db.scalars(
        select(AuditEvent.actor_id)
        .where(
            AuditEvent.organization_id == org_id,
            AuditEvent.action == "rfq.sent",
            AuditEvent.entity_id == rfq_id,
        )
        .order_by(AuditEvent.id.desc())
    ).first()
    if not actor_id or actor_id == "system":
        return None
    user = users_repo.get_user(db, actor_id)
    return user if user is not None and user.organization_id == org_id else None


def _sender_for(db: Session, org_id: str):
    """The org's agent inbox (AgentMail: one inbox per org), or the mock."""
    return rfq_sender.get_sender(db, org_id)


def _package_awarded(db: Session, org_id: str, rfq: dict) -> bool:
    decision = decisions_repo.latest_for_package(db, org_id, rfq["projectId"], rfq["package"])
    return bool(decision) and (decision.get("status") or "active") == "active"


def _send_nudge(
    db: Session,
    org_id: str,
    rfq: dict,
    recipients: List[dict],
    recipient: dict,
    n: int,
    now: datetime,
    *,
    sender,
    buyer,
    actor,
) -> None:
    """Write the intent, send in thread, then complete the intent. Raises on a
    failed send (the intent stays and becomes retryable after INTENT_TIMEOUT)."""
    rfq_id = rfq["id"]
    followups = [f for f in (recipient.get("followups") or []) if f.get("messageId")]
    intent = {"n": n, "sentAt": _iso(now), "messageId": None}
    followups.append(intent)
    recipient["followups"] = followups
    rfqs_repo.save_recipients(db, org_id, rfq_id, recipients)

    subject, body = draft_followup(rfq, recipient, n, buyer=buyer)
    sent = sender.send(
        recipient["email"], subject, body,
        from_addr=rfq_sender.from_header(buyer),
        cc=getattr(buyer, "cc_email", None),
        thread_id=recipient.get("threadId"),
        in_reply_to=recipient.get("messageId") or None,
    )
    intent["messageId"] = sent.message_id or f"sent-{_iso(now)}"
    ids = list(recipient.get("outboundMessageIds") or [])
    if sent.message_id and sent.message_id not in ids:
        # Ingest skips our own outbound ids, same as award notices.
        ids.append(sent.message_id)
        recipient["outboundMessageIds"] = ids
    rfqs_repo.save_recipients(db, org_id, rfq_id, recipients)

    supplier = recipient.get("name") or recipient["email"]
    package = _package_name(rfq)
    audit_repo.log(
        db, org_id, actor, AUDIT_ACTION, "rfq", rfq_id, project_id=rfq["projectId"],
        detail={
            "email": recipient["email"], "supplier": supplier, "n": n,
            "max": settings.followup_max, "messageId": intent["messageId"],
            "cc": getattr(buyer, "cc_email", None), "mock": bool(getattr(sender, "mocked", False)),
        },
    )
    notify.emit(db, notify.Notice(
        org_id=org_id,
        kind=FOLLOWUP_SENT,
        title=f"{package}: chased {supplier} (nudge {n} of {settings.followup_max})",
        project_id=rfq["projectId"],
        lines=[f"Replied in the RFQ thread to {recipient['email']}"],
        meta={"rfqId": rfq_id, "email": recipient["email"], "n": n},
    ))


def chase_rfq(
    db: Session,
    org_id: str,
    rfq_id: str,
    *,
    now: Optional[datetime] = None,
    force: bool = False,
    actor=None,
) -> FollowupRunSummary:
    """Nudge every outstanding recipient of one RFQ that is due. `force`
    ignores the due time and the send window (the dashboard's "chase now")
    but still respects replies, the max, and in-flight intents."""
    now = _aware(now) if now is not None else _utcnow()
    summary = FollowupRunSummary(rfqs_scanned=1)
    with locks.exclusive(f"rfq-followup:{org_id}:{rfq_id}", "This RFQ is already being chased"):
        rfq = rfqs_repo.get_rfq(db, org_id, rfq_id)
        if rfq is None or rfq["status"] not in _SENT_STATUSES or _package_awarded(db, org_id, rfq):
            return summary
        recipients = rfq["recipients"]
        due: List[Tuple[dict, int]] = []
        for r in recipients:
            n, due_at = next_nudge(rfq, r)
            if n is None or (not force and now < due_at):
                continue
            if _pending_intent(r, now) is not None or has_replied(db, org_id, rfq_id, r):
                continue
            due.append((r, n))
        if not due:
            return summary
        buyer = _rfq_sender_user(db, org_id, rfq_id)
        sender = _sender_for(db, org_id)
        for r, n in due:
            try:
                _send_nudge(db, org_id, rfq, recipients, r, n, now, sender=sender, buyer=buyer, actor=actor)
                summary.nudges_sent += 1
            except Exception as exc:  # noqa: BLE001 - one dead address must not stop the rest
                logger.warning("Follow-up %d for RFQ %s to %s failed: %s", n, rfq_id, r.get("email"), exc)
                summary.errors.append(f"{rfq_id}:{r.get('email')}: {exc}")
    return summary


def run_due(db: Session, now: Optional[datetime] = None, tz=None) -> FollowupRunSummary:
    """One pass over every sent RFQ in every org. Outside the send window
    nothing goes out; the due recipients are only counted."""
    now = _aware(now) if now is not None else _utcnow()
    summary = FollowupRunSummary()
    inside = within_send_window(now, tz)
    pairs = db.execute(select(Rfq.organization_id, Rfq.id).where(Rfq.status.in_(_SENT_STATUSES))).all()
    for org_id, rfq_id in pairs:
        summary.rfqs_scanned += 1
        if not inside:
            rfq = rfqs_repo.get_rfq(db, org_id, rfq_id)
            if rfq is None or _package_awarded(db, org_id, rfq):
                continue
            for r in rfq["recipients"]:
                n, due_at = next_nudge(rfq, r)
                if n is not None and now >= due_at and not has_replied(db, org_id, rfq_id, r):
                    summary.skipped_outside_hours += 1
            continue
        try:
            one = chase_rfq(db, org_id, rfq_id, now=now)
        except HTTPException:
            # Another worker holds this RFQ's lock; it will be seen next tick.
            continue
        except Exception as exc:  # noqa: BLE001 - keep scanning the other RFQs
            logger.exception("Follow-up pass failed for RFQ %s", rfq_id)
            summary.errors.append(f"{rfq_id}: {exc}")
            continue
        summary.nudges_sent += one.nudges_sent
        summary.errors.extend(one.errors)
    return summary


def status_for(db: Session, org_id: str, rfq: dict) -> List[dict]:
    """Per-recipient follow-up state for the dashboard."""
    out = []
    awarded = _package_awarded(db, org_id, rfq)
    for r in rfq["recipients"]:
        replied = has_replied(db, org_id, rfq["id"], r)
        n, due_at = next_nudge(rfq, r)
        sent_at = recipient_sent_at(rfq, r)
        out.append({
            "email": r.get("email") or "",
            "supplierName": r.get("name") or "",
            "sentAt": _iso(sent_at) if sent_at else None,
            "repliedAt": r.get("repliedAt") or None,
            "replied": replied,
            "followups": list(r.get("followups") or []),
            "nextDueAt": _iso(due_at) if (due_at and not replied and not awarded) else None,
        })
    return out


def tick() -> None:
    """Scheduler entry point: one pass on a fresh session."""
    with SessionLocal() as db:
        summary = run_due(db)
    if summary.nudges_sent or summary.errors:
        logger.info("Follow-up pass: %s", summary.to_dict())


if settings.followup_enabled:
    scheduler.register("rfq-followups", settings.followup_poll_interval_s, tick)
