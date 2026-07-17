"""Build a per-package RFQ draft from the project, BOM line items, and suppliers.

If OpenAI is configured the body is written by gpt-4.1; otherwise a deterministic
template is used (mock-safe). Recipients are the chosen suppliers that have an
email, capped to a sensible 5–10.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import settings

_MAX_RECIPIENTS = 10


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


def _opening_sentence(location: str) -> str:
    """Lead sentence for the RFQ body, naming the city of installation when known.

    Suppliers ask for the install location to quote the correct specs, so we state
    it up front rather than making them reply to ask.
    """
    if location:
        return (
            f"We are requesting a quote for material to be installed in {location}. "
            "Please provide unit pricing, current lead times, freight charges, "
            "available substitution options, and quote validity for the following items:"
        )
    return (
        "We are requesting a quote. Please provide unit pricing, current lead times, "
        "freight charges, available substitution options, and quote validity for the "
        "following items:"
    )


def _template_body(items_text: str, location: str) -> str:
    return (
        f"{_opening_sentence(location)}\n\n"
        f"{items_text}\n\n"
        "Your prompt response is appreciated. Please let us know if you need "
        "additional information to complete your quote."
    )


def _llm_body(
    project_name: str, package_label: str, items_text: str, location: str
) -> Optional[str]:
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
        )
        location_instruction = (
            f"The material will be installed in {location}; state this city of "
            "installation in the opening sentence so the supplier can quote the "
            "correct specs. "
            if location
            else ""
        )
        prompt = (
            "Write a concise, professional construction Request-for-Quote email body "
            f"for the '{package_label}' package on project '{project_name}'. "
            f"{location_instruction}"
            "Open with a single sentence requesting a quote and asking for unit "
            "pricing, current lead times, freight charges, available substitution "
            "options, and quote validity. Then list the line items exactly as a "
            "bullet list (one item per line, '- <description> — <quantity>'). Close "
            "with a brief sentence inviting follow-up if more information is needed. "
            "Do not add a greeting, project header, or signature. Match this style:\n\n"
            f"{_opening_sentence(location)}\n\n"
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
) -> RfqDraft:
    """Build subject/body/recipients for an RFQ. Never raises."""
    project_name = project.get("name", "Project")
    location = _clean_location(project)
    items_text = _format_items(line_items)
    subject = f"RFQ: {package_label} — {project_name}"

    body = _llm_body(project_name, package_label, items_text, location) or _template_body(
        items_text, location
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
