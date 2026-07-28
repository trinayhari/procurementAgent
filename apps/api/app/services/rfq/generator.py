"""Build a per-package RFQ draft from the project, BOM line items, and suppliers.

If OpenAI is configured the body is written by gpt-4.1; otherwise a deterministic
template is used (mock-safe). Recipients are the chosen suppliers that have an
email, capped to a sensible 5–10.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import settings

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
    if name and company:
        return f"My name is {name} with {company}."
    if name:
        return f"My name is {name}."
    if company:
        return f"I am writing on behalf of {company}."
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


def _opening_paragraph(
    buyer, package_label: str, project_name: str, location: str
) -> str:
    """Who is writing, what they need, and the ask.

    Both body paths are built from this one string, so the LLM and the fallback
    template can't drift apart in what they tell the supplier.
    """
    parts = (
        _buyer_intro(buyer),
        _request_sentence(package_label, project_name, location),
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
        return (resp.choices[0].message.content or "").strip() or None
    except Exception:
        return None


def generate_rfq_draft(
    project: dict,
    package_label: str,
    line_items: List[dict],
    suppliers: List[dict],
    buyer=None,
) -> RfqDraft:
    """Build subject/body/recipients for an RFQ. Never raises.

    `buyer` is the requesting user (anything carrying `.name` / `.company`); the
    body introduces them so the supplier isn't quoting an anonymous stranger.
    """
    project_name = (project.get("name") or "").strip()
    location = _clean_location(project)
    items_text = _format_items(line_items)
    subject = f"RFQ: {package_label} — {project_name or 'Project'}"

    opening = _opening_paragraph(buyer, package_label, project_name, location)
    body = _llm_body(package_label, items_text, opening) or _template_body(
        opening, items_text
    )

    recipients = [
        {
            "supplierId": s.get("id"),
            "name": s.get("name"),
            "email": s.get("email"),
        }
        for s in suppliers
        if s.get("email")
    ][:_MAX_RECIPIENTS]

    return RfqDraft(
        subject=subject,
        body=body,
        line_items=line_items,
        recipients=recipients,
    )
