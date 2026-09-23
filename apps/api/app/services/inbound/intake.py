"""Customer requests sent to the agent by email (owned by the intake work).

A PM forwards the plan set with a sentence of context ("Riverside WTP, need
these by the 14th") and the agent takes it from there: find or create the
project, file each attachment as a document with a guessed plan type, start
extraction exactly as an upload would, and reply in the same thread with
what it understood. A message with no attachment is logged on the project
as a note and acknowledged the same way.

attribute(): the sender is a known User, set organization_id, return True.
handle(): the email adapter over `handle_request`, which is the transport
agnostic core (Slack calls it with files it downloaded itself).
"""
from __future__ import annotations

import calendar
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.dates import humanize
from app.models.inbound_email import InboundEmail
from app.models.user import User
from app.repositories import events as events_repo
from app.repositories import projects as projects_repo
from app.repositories import users as users_repo
from app.services import documents_intake, extraction, notify, storage

logger = logging.getLogger("procureai.inbound.intake")


# ------------------------------------------------------------------ results
@dataclass
class IntakeResult:
    project_id: str
    project_created: bool
    documents: List[dict] = field(default_factory=list)  # {id, name, planType}
    need_by: Optional[str] = None  # YYYY-MM-DD
    summary: str = ""


@dataclass
class ResolvedProject:
    project_id: str
    name: str
    created: bool
    need_by: Optional[str] = None
    location: Optional[str] = None
    notes: str = ""


# ------------------------------------------------------------- attribution
def attribute(db: Session, msg: InboundEmail) -> bool:
    """A message from a registered user is an intake request for their org."""
    if not msg.from_email:
        return False
    user = users_repo.get_by_email(db, msg.from_email)
    if user is None:
        return False
    msg.organization_id = user.organization_id
    return True


# ------------------------------------------------------ subject / need-by
_PREFIX_RE = re.compile(r"^\s*(?:(?:re|fwd?|fw|aw|wg)\s*:\s*)+", re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def clean_subject(subject: str) -> str:
    """Drop reply/forward prefixes and surrounding noise, keep the human text."""
    s = _PREFIX_RE.sub("", subject or "")
    s = re.sub(r"\s+", " ", s).strip(" \t-:;,.")
    return s


def normalise(name: str) -> str:
    """Case, punctuation and whitespace insensitive key for name matching."""
    return _NON_WORD_RE.sub(" ", (name or "").lower()).strip()


_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9

_TRIGGER = r"\b(?:by|before|due|deadline|until|needed|on)\b[\s:]*(?:the\s+)?"
_MONTH_NAME = (
    r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DAY = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s*(?P<year>\d{4}))?"

# Tried in order, most specific first. Every form needs a trigger word so a
# stray number in the body ("by 3 suppliers") is not read as a date.
_NEED_BY_PATTERNS = [
    # by 2026-10-14
    re.compile(_TRIGGER + r"(?P<iso>\d{4}-\d{2}-\d{2})\b", re.IGNORECASE),
    # by Oct 14 / before October 14th, 2026
    re.compile(_TRIGGER + _MONTH_NAME + r"\.?\s+" + _DAY + _YEAR + r"\b", re.IGNORECASE),
    # by the 14th of October
    re.compile(_TRIGGER + _DAY + r"\s+(?:of\s+)?" + _MONTH_NAME + _YEAR + r"\b", re.IGNORECASE),
    # by 10/14 or 10/14/2026
    re.compile(_TRIGGER + r"(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2,4}))?\b", re.IGNORECASE),
    # by the 14th (the article or the ordinal suffix is required)
    re.compile(
        r"\b(?:by|before|due|until)\b[\s:]*(?:the\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?|(?P<day2>\d{1,2})(?:st|nd|rd|th))\b",
        re.IGNORECASE,
    ),
]


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_need_by(text: str, today: Optional[date] = None) -> Optional[str]:
    """Best-effort need-by date from phrases like "by the 14th", "before Oct
    14", "need it by 10/14". Day-only and month/day forms resolve to the next
    occurrence on or after `today`. None when nothing convincing is found."""
    if not text:
        return None
    today = today or date.today()
    for pattern in _NEED_BY_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        g = m.groupdict()
        if g.get("iso"):
            try:
                return date.fromisoformat(g["iso"]).isoformat()
            except ValueError:
                continue
        if g.get("m") and g.get("d"):
            month, day = int(g["m"]), int(g["d"])
            year = g.get("y")
            if year:
                year = int(year)
                year = year + 2000 if year < 100 else year
                found = _safe_date(year, month, day)
            else:
                found = _next_occurrence(today, month, day)
            if found:
                return found.isoformat()
            continue
        day = int(g.get("day") or g.get("day2") or 0)
        if not 1 <= day <= 31:
            continue
        mon = g.get("mon")
        if mon:
            month = _MONTHS.get(mon.lower().rstrip("."))
            if not month:
                continue
            year = g.get("year")
            found = _safe_date(int(year), month, day) if year else _next_occurrence(today, month, day)
        else:
            # "by the 14th": this month if still ahead, else next month.
            found = _safe_date(today.year, today.month, day)
            if found is None or found < today:
                y, mth = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
                found = _safe_date(y, mth, day)
        if found:
            return found.isoformat()
    return None


def _next_occurrence(today: date, month: int, day: int) -> Optional[date]:
    found = _safe_date(today.year, month, day)
    if found is None or found < today:
        found = _safe_date(today.year + 1, month, day)
    return found


# ------------------------------------------------------ plan type inference
_SLOT_WORDS = {
    "site_plan": re.compile(r"\b(?:site|civil|grading|utilit(?:y|ies)|drainage|storm|sewer)\b", re.IGNORECASE),
    "electrical_plan": re.compile(r"\b(?:electrical|electric|lighting|power)\b", re.IGNORECASE),
    "building_plan": re.compile(r"\b(?:building|arch|architectural|structural|framing|floor\s+plans?)\b", re.IGNORECASE),
}
# Drawing sheet prefixes: C-101 civil, E-201 electrical, A-101 / S-201 building.
_SHEET_PREFIX = {"c": "site_plan", "e": "electrical_plan", "a": "building_plan", "s": "building_plan"}
_SHEET_RE = re.compile(r"(?<![a-z0-9])([aces])[-_ ]?\d{1,3}(?:\.\d+)?(?![a-z0-9])", re.IGNORECASE)


def _keyword_slot(text: str) -> Optional[str]:
    """The one plan slot `text` clearly names, or None when it names several
    (or none): a combined set is not a site plan just because "site" appears."""
    hits = [key for key, pattern in _SLOT_WORDS.items() if pattern.search(text or "")]
    return hits[0] if len(hits) == 1 else None


def _slot_by_discipline() -> dict:
    """{"civil": "site_plan", "structural": "building_plan", ...} from the
    registry, so a new plan type is picked up without touching this module."""
    out = {}
    for spec in extraction.registry.all_specs():
        if not spec.enabled:
            continue
        for discipline in spec.sheet_disciplines:
            out.setdefault(discipline, spec.key)
    return out


def classify_from_content(locator: str, *, max_pages: int = 12) -> Optional[str]:
    """The plan type a document's own sheets say it is, or None.

    A plan set is usually named for the submittal ("54-61 APPROVAL PLAN.pdf"),
    not the discipline, so the filename often carries no signal at all. The
    sheets themselves do: the extraction pipeline already classifies a page by
    its title block and sheet number, so reuse that and take the discipline
    that wins across the set. Best effort: any failure means "unknown", and
    the caller falls back to an additional document.
    """
    from app.services.extraction import pdf, sheets

    slots = _slot_by_discipline()
    tally: dict = {}
    try:
        with storage.local_copy(locator) as path:
            pages = pdf.extract_text_pages(path, max_pages=max_pages)
    except Exception:  # noqa: BLE001 - classification must never break intake
        logger.warning("intake: could not read %s for classification", locator, exc_info=True)
        return None
    for page in pages:
        discipline = sheets.classify_page(page.get("text") or "")
        slot = slots.get(discipline or "")
        if slot:
            tally[slot] = tally.get(slot, 0) + 1
    if not tally:
        return None
    return max(tally, key=lambda k: tally[k])


def infer_plan_type(filename: str, text: str = "", locator: Optional[str] = None) -> str:
    """Guess the registry plan type for an attachment.

    The filename decides first (keywords, then a sheet prefix such as E-101);
    the message text breaks a tie only when the filename says nothing. When
    neither says anything and `locator` is given, the document's own sheets
    decide (classify_from_content). Files the extractor cannot read, and
    disabled or still-ambiguous cases, go to "other".
    """
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in documents_intake.EXTRACTABLE_EXTENSIONS:
        return "other"
    stem = os.path.splitext(os.path.basename(filename))[0]
    key = _keyword_slot(stem.replace("_", " ").replace("-", " "))
    if key is None:
        sheet = _SHEET_RE.search(stem)
        if sheet:
            key = _SHEET_PREFIX.get(sheet.group(1).lower())
    if key is None:
        key = _keyword_slot(text)
    if key is None and locator:
        key = classify_from_content(locator)
    if key is None:
        return "other"
    spec = extraction.registry.get(key)
    return key if spec is not None and spec.enabled else "other"


# --------------------------------------------------------- project resolve
def _match_existing(projects: List[dict], subject: str, text: str) -> Optional[dict]:
    """Exact normalised name match on the subject, then the longest project
    name contained in the subject or the first lines of the body."""
    cleaned = normalise(clean_subject(subject))
    by_key = {normalise(p["name"]): p for p in projects if p.get("name")}
    if cleaned and cleaned in by_key:
        return by_key[cleaned]
    haystack = " " + cleaned + " " + normalise((text or "")[:500]) + " "
    best = None
    for key, project in by_key.items():
        if len(key) < 4 or f" {key} " not in haystack:
            continue
        if best is None or len(key) > len(normalise(best["name"])):
            best = project
    return best


_LLM_PROMPT = (
    "You are the intake desk for a construction procurement team. A colleague "
    "emailed a request. Decide which project it is about.\n\n"
    "Existing projects (id: name, location):\n{projects}\n\n"
    "Subject: {subject}\nMessage:\n{text}\n\n"
    "Reply with JSON only: {{\"project_name\": str, \"is_existing\": bool, "
    "\"existing_project_id\": str|null, \"location\": str|null, "
    "\"need_by\": \"YYYY-MM-DD\"|null, \"notes\": str}}. "
    "Use an existing project only when the message clearly refers to it. "
    "Today is {today}."
)


def _llm_resolve(projects: List[dict], subject: str, text: str) -> Optional[dict]:
    """One short JSON call through the extraction service's OpenAI client.
    Returns None when the key is unset or the call fails; callers fall back."""
    if not settings.openai_api_key:
        return None
    try:
        from app.services.extraction import vision

        client = vision._client()
        listing = "\n".join(f"{p['id']}: {p['name']}, {p.get('loc') or 'TBD'}" for p in projects) or "(none)"
        completion = client.chat.completions.create(
            model=settings.openai_vision_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": _LLM_PROMPT.format(
                    projects=listing, subject=subject or "(no subject)",
                    text=(text or "(empty)")[:4000], today=date.today().isoformat(),
                ),
            }],
        )
        return json.loads(completion.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001 - the deterministic path always works
        logger.exception("intake: project resolution call failed")
        return None


def resolve_project(
    db: Session, org_id: str, subject: str, text: str, *, sender_name: str = ""
) -> ResolvedProject:
    """Find the project a request is about, or create one named from the subject."""
    projects = projects_repo.list_projects(db, org_id)
    by_id = {p["id"]: p for p in projects}
    need_by = parse_need_by(text) or parse_need_by(subject)

    match = _match_existing(projects, subject, text)
    if match is not None:
        return ResolvedProject(match["id"], match["name"], False, need_by=need_by)

    name, location, notes = clean_subject(subject), None, ""
    guess = _llm_resolve(projects, subject, text)
    if guess:
        existing = guess.get("existing_project_id") if guess.get("is_existing") else None
        if existing in by_id:
            p = by_id[existing]
            return ResolvedProject(
                p["id"], p["name"], False,
                need_by=guess.get("need_by") or need_by, notes=guess.get("notes") or "",
            )
        name = (guess.get("project_name") or "").strip() or name
        location = guess.get("location") or None
        need_by = guess.get("need_by") or need_by
        notes = guess.get("notes") or ""

    if not name:
        name = f"Request from {sender_name}" if sender_name else "New request"
    # Names are matched case-insensitively above, so a second look here only
    # guards the LLM naming an existing project without flagging it.
    for p in projects:
        if normalise(p["name"]) == normalise(name):
            return ResolvedProject(p["id"], p["name"], False, need_by=need_by, notes=notes)
    project = projects_repo.create_project(db, org_id, name=name, loc=location or "TBD")
    events_repo.log(
        db, org_id, project["id"],
        title="Project created", icon="sparkles", tone="ai", meta=project["name"],
    )
    return ResolvedProject(
        project["id"], project["name"], True, need_by=need_by, location=location, notes=notes,
    )


# ------------------------------------------------------------------ core
_NOTE_CHARS = 200


def _plan_label(plan_type: str) -> str:
    spec = extraction.registry.get(plan_type)
    return spec.label if spec is not None else plan_type


def _file_line(name: str, plan_type: str, pages: int) -> str:
    line = f"{name}: {_plan_label(plan_type)}"
    if pages:
        line += f", {pages} page{'s' if pages != 1 else ''}"
    return line


def handle_request(
    db: Session,
    *,
    org_id: str,
    user: Optional[User],
    text: str,
    subject: str,
    attachments: List[dict],
    thread: Optional[notify.ThreadRef],
    on_project: Optional[Callable[[str, bool], None]] = None,
    project_id: Optional[str] = None,
) -> IntakeResult:
    """Run one intake request end to end and acknowledge it on `thread`.

    `attachments` are already in storage: dicts with filename, mimeType,
    size, locator. `on_project(project_id, created)` fires as soon as the
    project is known, before any document work or notice, so a transport can
    persist the link the reply-threading later relies on.

    `project_id` names the project outright and skips resolution: the caller
    already knows which one this belongs to (a Slack channel linked with
    `/proq link`, a reply in a thread we started). Guessing from the subject
    in that case invents a project named after the channel and files the work
    somewhere nobody is looking.
    """
    sender_name = (user.name if user and user.name else (user.email if user else "")) or ""
    resolved = None
    if project_id:
        row = projects_repo.get_project(db, org_id, project_id)
        if row is not None:
            resolved = ResolvedProject(
                row["id"], row["name"], False,
                need_by=parse_need_by(text) or parse_need_by(subject),
            )
        else:
            logger.warning("intake: project %s not found in org %s, resolving by name", project_id, org_id)
    if resolved is None:
        resolved = resolve_project(db, org_id, subject, text, sender_name=sender_name)
    if resolved.need_by:
        # The PM's date wins: "pour is the 21st" in a later email is an update,
        # not a conflict. RFQs already drafted keep their own copy.
        projects_repo.update_project(db, org_id, resolved.project_id, need_by=resolved.need_by)
    if on_project is not None:
        on_project(resolved.project_id, resolved.created)

    if not attachments:
        note = " ".join((text or "").split())[:_NOTE_CHARS] or clean_subject(subject) or "(empty message)"
        events_repo.log(
            db, org_id, resolved.project_id,
            title=f"Note from {sender_name or 'the team'}: {note}",
            icon="message", tone="blue", meta=clean_subject(subject),
        )
        summary = f"Note logged on {resolved.name}"
        notify.emit(db, notify.Notice(
            org_id=org_id, project_id=resolved.project_id, kind="intake.noted",
            title=f"Noted on {resolved.name}",
            lines=[
                "I logged your message on the project as a note.",
                "Send plans or an addendum in this thread and I will pick them up.",
            ],
            thread=thread,
            meta={"projectCreated": resolved.created, "needBy": resolved.need_by},
        ))
        return IntakeResult(resolved.project_id, resolved.created, [], resolved.need_by, summary)

    documents: List[dict] = []
    lines: List[str] = []
    taken_slots: set = set()
    analyzable = False
    drafting_bom = False
    for att in attachments:
        filename = os.path.basename(att.get("filename") or "attachment")
        locator = att.get("locator") or ""
        plan_type = infer_plan_type(filename, text, locator=locator)
        # One file per slot within a message: a second "site" PDF would
        # otherwise replace the first before it was even read.
        if plan_type != "other" and plan_type in taken_slots:
            plan_type = "other"
        try:
            doc = documents_intake.attach_stored_file(
                db, org_id, resolved.project_id,
                locator=locator, filename=filename, plan_type=plan_type,
                actor=user, size=att.get("size"),
            )
        except documents_intake.AttachError as exc:
            # A BOM slot that will not take the file (corrupt PDF): file it as
            # an additional document rather than dropping it on the floor.
            if plan_type == "other":
                logger.warning("intake: could not attach %s: %s", filename, exc)
                lines.append(f"{filename}: could not be read, skipped")
                continue
            plan_type = "other"
            try:
                doc = documents_intake.attach_stored_file(
                    db, org_id, resolved.project_id,
                    locator=locator, filename=filename, plan_type=plan_type,
                    actor=user, size=att.get("size"),
                )
            except documents_intake.AttachError as exc2:
                logger.warning("intake: could not attach %s: %s", filename, exc2)
                lines.append(f"{filename}: could not be read, skipped")
                continue
        taken_slots.add(plan_type)
        analyzable = analyzable or doc.processing
        spec = extraction.registry.get(plan_type)
        if doc.processing and spec is not None and spec.categories:
            drafting_bom = True
        documents.append({"id": doc.id, "name": doc.name, "planType": plan_type})
        lines.append(_file_line(filename, plan_type, doc.pages or 0))

    if resolved.need_by:
        lines.append(f"Need by: {humanize(resolved.need_by)}")
    if drafting_bom:
        lines.append("Drafting the bill of materials now, I'll reply here when it's ready.")
    elif analyzable:
        # Readable, but filed where no take-off happens. Saying "drafting the
        # BOM" here promises a reply that never comes.
        lines.append(
            "Filed as an additional document, so I am not taking off quantities from it. "
            "If it is a plan set, reply with site, building or electrical and I'll read it as one."
        )
    else:
        lines.append("Filed on the project. Nothing to extract from these files.")

    summary = (
        f"{resolved.name}{' (new project)' if resolved.created else ''}: "
        f"{len(documents)} file{'s' if len(documents) != 1 else ''}"
    )
    if documents:
        summary += " (" + ", ".join(f"{d['name']} as {_plan_label(d['planType'])}" for d in documents) + ")"
    if resolved.need_by:
        summary += f", need by {resolved.need_by}"

    notify.emit(db, notify.Notice(
        org_id=org_id, project_id=resolved.project_id, kind="intake.received",
        title=f"Got it: {resolved.name}",
        lines=lines,
        thread=thread,
        meta={
            "projectCreated": resolved.created, "needBy": resolved.need_by,
            "documentIds": [d["id"] for d in documents],
        },
    ))
    return IntakeResult(resolved.project_id, resolved.created, documents, resolved.need_by, summary)


# --------------------------------------------------------------- adapter
def _thread_for(msg: InboundEmail) -> notify.ThreadRef:
    return notify.ThreadRef(
        channel="email",
        email_message_id=msg.rfc_message_id or "",
        email_address=msg.from_email or "",
        email_subject=msg.subject or "",
    )


def _attachments_of(msg: InboundEmail) -> List[dict]:
    try:
        items = json.loads(msg.attachments or "[]")
    except ValueError:
        return []
    return [a for a in items if isinstance(a, dict) and a.get("locator")]


def handle(db: Session, msg: InboundEmail) -> None:
    """Process one intake email. Idempotent on `processed_at`; a failure is
    recorded on the row (`error`, `attempts`) and never raised: the webhook
    that called us has already accepted the message."""
    if msg.processed_at is not None:
        return
    try:
        if not msg.organization_id:
            raise RuntimeError("intake message is not attributed to an organization")
        user = users_repo.get_by_email(db, msg.from_email) if msg.from_email else None
        if user is not None and user.organization_id != msg.organization_id:
            user = None

        def _remember_project(project_id: str, _created: bool) -> None:
            # Committed before any notice goes out: the email notifier finds
            # the originating thread through this row.
            msg.project_id = project_id
            db.add(msg)
            db.commit()

        handle_request(
            db,
            org_id=msg.organization_id,
            user=user,
            text=msg.text or "",
            subject=msg.subject or "",
            attachments=_attachments_of(msg),
            thread=_thread_for(msg),
            on_project=_remember_project,
        )
        msg.processed_at = datetime.now(timezone.utc)
        msg.error = None
        db.add(msg)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - recorded on the row for a retry
        logger.exception("intake failed for inbound %s", msg.id)
        db.rollback()
        msg.error = str(exc)[:2000]
        msg.attempts = (msg.attempts or 0) + 1
        db.add(msg)
        db.commit()
