"""Build a per-package RFQ draft from the project, BOM line items, and suppliers.

If OpenAI is configured the body is written by gpt-4.1; otherwise a deterministic
template is used (mock-safe). Recipients are the chosen suppliers that have an
email, capped to a sensible 5–10.
"""
from dataclasses import dataclass, field
import re
from typing import List, Optional

from app.config import settings
from app.core.dates import humanize
from app.services import llm_health

_MAX_RECIPIENTS = 10

_ASK = (
    "Please provide unit pricing, current lead times, freight charges, "
    "available substitution options, and quote validity for the following items:"
)


@dataclass
class RfqDraft:
    subject: str
    body: str
    line_items: List[dict] = field(default_factory=list)
    recipients: List[dict] = field(default_factory=list)


def _format_items(line_items: List[dict]) -> str:
    lines = []
    for it in line_items:
        name = it.get("n") or it.get("name") or ""
        qty = it.get("q") or it.get("quantity") or ""
        lines.append(f"- {name} — {qty}" if qty else f"- {name}")
    return "\n".join(lines)


def _clean_location(project: dict) -> str:
    """The project's city of installation, or "" when it isn't set.

    Projects store location as a freeform "City, State" string in `loc` and fall
    back to the placeholder "—" when unknown; treat that (and blanks) as absent.
    """
    loc = (project.get("loc") or "").strip()
    return "" if loc in ("", "—") else loc


def _buyer_intro(buyer) -> str:
    """"My name is … with …" — the supplier has to know who is asking.

    Name and company are both optional on a user, so each clause drops out on its
    own; we never introduce the buyer with a blank or an invented company.
    """
    name = (getattr(buyer, "name", "") or "").strip()
    company = (getattr(buyer, "company", "") or "").strip()
    # "Meridian Civil Co." already ends the sentence — don't add a second stop.
    stop = "" if company.endswith(".") else "."
    if name and company:
        return f"My name is {name} with {company}{stop}"
    if name:
        return f"My name is {name}."
    if company:
        return f"I am writing on behalf of {company}{stop}"
    return ""


def _material_phrase(package_label: str) -> str:
    """The package label as it reads mid-sentence — "water utilities".

    Labels are title-cased for the UI ("Water Utilities") but a custom BOM is
    often named after an acronym ("PVC Pipe"), so all-caps words keep their case.
    """
    return " ".join(
        w if w.isupper() else w.lower() for w in (package_label or "").split()
    )


def _request_sentence(package_label: str, project_name: str, location: str) -> str:
    """Names the material and the job it is for — a supplier's first two questions.

    Material, project name, and city are each optional; a missing one drops its
    clause instead of leaving a hole ("our  project in ."), so the sentence stays
    grammatical however little we know.
    """
    material = _material_phrase(package_label)
    sentence = "We are looking for a supplier"
    if material:
        sentence += f" of {material}"
    if project_name and location:
        sentence += f" for our {project_name} project in {location}"
    elif project_name:
        sentence += f" for our {project_name} project"
    elif location:
        sentence += f" for our project in {location}"
    return f"{sentence}."


def _need_by_sentence(need_by: Optional[str]) -> str:
    """'We need the material on site by October 14, 2026.' or ''."""
    when = humanize(need_by)
    return f"We need the material on site by {when}, so please include your lead time." if when else ""


def _opening_paragraph(
    buyer, package_label: str, project_name: str, location: str, need_by: Optional[str] = None
) -> str:
    """Who is writing, what they need, when, and the ask.

    Both body paths are built from this one string, so the LLM and the fallback
    template can't drift apart in what they tell the supplier.
    """
    parts = (
        _buyer_intro(buyer),
        _request_sentence(package_label, project_name, location),
        _need_by_sentence(need_by),
        _ASK,
    )
    return " ".join(p for p in parts if p)


def _template_body(opening: str, items_text: str) -> str:
    return (
        f"{opening}\n\n"
        f"{items_text}\n\n"
        "Your prompt response is appreciated. Please let us know if you need "
        "additional information to complete your quote."
    )


def _llm_body(package_label: str, items_text: str, opening: str) -> Optional[str]:
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
        )
        prompt = (
            "Write a concise, professional construction Request-for-Quote email body "
            f"for the '{package_label}' package. Open with the paragraph below "
            "verbatim — it names the buyer, the material, and the project, so do not "
            "reword it or add details it leaves out. Then list the line items exactly "
            "as a bullet list (one item per line, '- <description> — <quantity>'). "
            "Close with a brief sentence inviting follow-up if more information is "
            "needed. Do not add a greeting, project header, or signature. Match this "
            "style:\n\n"
            f"{opening}\n\n"
            "- <item> — <qty>\n\n"
            "Your prompt response is appreciated. Please let us know if you need "
            "additional information to complete your quote.\n\n"
            "Use exactly these line items:\n\n"
            f"{items_text}\n\n"
            "Return only the email body (no subject line)."
        )
        resp = client.chat.completions.create(
            model=settings.openai_vision_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=600,
        )
        llm_health.record_success()
        return (resp.choices[0].message.content or "").strip() or None
    except Exception as exc:
        llm_health.record_failure(exc, "RFQ body generator")
        return None


def generate_rfq_draft(
    project: dict,
    package_label: str,
    line_items: List[dict],
    suppliers: List[dict],
    buyer=None,
    need_by: Optional[str] = None,
) -> RfqDraft:
    """Build subject/body/recipients for an RFQ. Never raises.

    `buyer` is the requesting user (anything carrying `.name` / `.company`); the
    body introduces them so the supplier isn't quoting an anonymous stranger.
    `need_by` (ISO date) is quoted so the supplier prices lead time against it.
    """
    project_name = (project.get("name") or "").strip()
    location = _clean_location(project)
    items_text = _format_items(line_items)
    subject = f"RFQ: {package_label} — {project_name or 'Project'}"

    opening = _opening_paragraph(buyer, package_label, project_name, location, need_by)
    body = _llm_body(package_label, items_text, opening) or _template_body(
        opening, items_text
    )

    recipients = _recipients(suppliers)

    return RfqDraft(
        subject=subject,
        body=body,
        line_items=line_items,
        recipients=recipients,
    )


def _recipients(suppliers: List[dict]) -> List[dict]:
    return [
        {
            "supplierId": s.get("id"),
            "name": s.get("name"),
            "email": s.get("email"),
        }
        for s in suppliers
        if s.get("email")
    ][:_MAX_RECIPIENTS]


# ------------------------------------------------------------- subcontractor

_SUB_ASK = (
    "Please provide your lump-sum bid price, current schedule availability, "
    "inclusions and exclusions, and how long your bid remains valid."
)


def _sub_request_sentence(trade_label: str, project_name: str, location: str) -> str:
    """Names the trade and the job it is for — a sub's first two questions."""
    trade = _material_phrase(trade_label)
    sentence = "We are seeking bids"
    if trade:
        sentence += f" from qualified {trade} subcontractors"
    if project_name and location:
        sentence += f" for our {project_name} project in {location}"
    elif project_name:
        sentence += f" for our {project_name} project"
    elif location:
        sentence += f" for our project in {location}"
    return f"{sentence}."


# Attachments are chosen in the review modal AFTER a draft is generated, so
# no template or model prompt ever mentions them. At send time the route adds
# ATTACHMENT_SENTENCE when files actually ride along (body_with_attachment_note)
# and persists the body that went out, so the draft, the stored RFQ and the
# thread all read exactly what the supplier received.
ATTACHMENT_SENTENCE = "Please review the attached project documents for additional detail."
_PROMPT_RESPONSE_RE = re.compile(r"Your prompt response is appreciated\.")


def _sub_need_by_sentence(need_by: Optional[str]) -> str:
    when = humanize(need_by)
    return f"The work needs to be complete by {when}." if when else ""


def _sub_template_body(opening: str, scope: str) -> str:
    return (
        f"{opening}\n\n"
        "Scope of work:\n"
        f"{scope}\n\n"
        "Your prompt response is appreciated. Please let us know if "
        "you need additional information to prepare your bid."
    )


_ATTACHMENT_NOTE_RE = re.compile(
    r"[^.\n]*\battached (?:project )?documents?\b[^.\n]*\.\s*", re.IGNORECASE
)


def body_without_attachment_note(body: str) -> str:
    """Drop any "attached project documents" sentence from a body.

    Backstop for drafts generated before templates stopped emitting the
    hedge ("Please review any attached …"): with nothing attached the email
    must never refer to documents that aren't there."""
    return _ATTACHMENT_NOTE_RE.sub("", body or "").rstrip(" ")


def body_with_attachment_note(body: str) -> str:
    """The body to send when documents ARE attached: one sentence pointing the
    supplier at them, placed just before "Your prompt response is
    appreciated." when that closing is present, else on its own line at the
    end. Idempotent — an old draft that already carries a note is normalised
    to the single current sentence."""
    base = body_without_attachment_note(body).rstrip()
    m = _PROMPT_RESPONSE_RE.search(base)
    if m:
        return base[: m.start()] + ATTACHMENT_SENTENCE + " " + base[m.start():]
    return f"{base}\n\n{ATTACHMENT_SENTENCE}" if base else ATTACHMENT_SENTENCE


def body_for_send(body: str, has_attachments: bool) -> str:
    """What actually goes on the wire (and is persisted onto the RFQ)."""
    return body_with_attachment_note(body) if has_attachments else body_without_attachment_note(body)


def _sub_llm_body(trade_label: str, scope: str, opening: str) -> Optional[str]:
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
        )
        prompt = (
            "Write a concise, professional construction bid-request (RFQ) email "
            f"body inviting a {trade_label} subcontractor to bid. Open with the "
            "paragraph below verbatim — it names the buyer, the trade, and the "
            "project, so do not reword it or add details it leaves out. Then "
            "include the scope of work below verbatim under a 'Scope of work:' "
            "heading. Do not mention attachments or documents. "
            "Close with a brief sentence inviting follow-up if more information "
            "is needed. Do not add a greeting, project header, or signature.\n\n"
            f"{opening}\n\n"
            "Scope of work:\n"
            f"{scope}\n\n"
            "Return only the email body (no subject line)."
        )
        resp = client.chat.completions.create(
            model=settings.openai_vision_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=600,
        )
        llm_health.record_success()
        return (resp.choices[0].message.content or "").strip() or None
    except Exception as exc:
        llm_health.record_failure(exc, "bid-request body generator")
        return None


def generate_sub_rfq_draft(
    project: dict,
    trade_label: str,
    scope: str,
    suppliers: List[dict],
    buyer=None,
    need_by: Optional[str] = None,
) -> RfqDraft:
    """Build subject/body/recipients for a subcontractor bid request. Never raises.

    Unlike a materials RFQ there are no line items: the user-written scope of
    work (plus any attached documents) carries the detail.
    """
    project_name = (project.get("name") or "").strip()
    location = _clean_location(project)
    scope = (scope or "").strip()
    subject = f"Bid Request: {trade_label} — {project_name or 'Project'}"

    parts = (
        _buyer_intro(buyer),
        _sub_request_sentence(trade_label, project_name, location),
        _sub_need_by_sentence(need_by),
        _SUB_ASK,
    )
    opening = " ".join(p for p in parts if p)
    body = _sub_llm_body(trade_label, scope, opening) or _sub_template_body(
        opening, scope
    )

    return RfqDraft(
        subject=subject,
        body=body,
        line_items=[],
        recipients=_recipients(suppliers),
    )
