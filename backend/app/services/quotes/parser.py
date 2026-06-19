"""Turn a supplier's reply (email body + attachment text) into a ParsedQuote.

Primary path: OpenAI Structured Outputs (same model/SDK as extraction). Fallback:
a regex pass that pulls the obvious dollar figures and a lead time, so ingest
still yields comparable numbers when no key is set or the model call fails.
"""
import re
from typing import Optional

from app.config import settings
from app.services.quotes.models import ParsedQuote

_SYSTEM = (
    "You read construction supplier quotes and extract the commercial terms. "
    "Return only numbers you are confident are correct; leave a field null if it "
    "is not clearly stated. Money is USD. Do not invent figures."
)

_MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
_LEAD_RE = re.compile(r"(\d{1,3})\s*(?:business\s*)?(?:day|days|wk|wks|week|weeks)", re.I)
_TOTAL_HINT = re.compile(r"(total|grand total|amount due)", re.I)
_FREIGHT_HINT = re.compile(r"(freight|shipping|delivery charge)", re.I)


def is_configured() -> bool:
    return bool(settings.openai_api_key)


def _llm_parse(text: str) -> Optional[ParsedQuote]:
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)
        completion = client.beta.chat.completions.parse(
            model=settings.openai_vision_model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Extract the quote terms from this supplier message:\n\n{text[:12000]}"},
            ],
            response_format=ParsedQuote,
            temperature=0,
            max_tokens=2000,
        )
        return completion.choices[0].message.parsed
    except Exception:
        return None


def _regex_parse(text: str) -> ParsedQuote:
    """Best-effort: largest dollar figure → total; a freight-tagged line → freight."""
    amounts = []
    for line in text.splitlines():
        for m in _MONEY_RE.finditer(line):
            try:
                amounts.append((float(m.group(1).replace(",", "")), line))
            except ValueError:
                continue

    total = freight = material = None
    if amounts:
        total = max(a for a, _ in amounts)
        for amt, line in amounts:
            if _FREIGHT_HINT.search(line):
                freight = amt
        if freight is not None and total is not None and total > freight:
            material = round(total - freight, 2)

    lead = None
    lm = _LEAD_RE.search(text)
    if lm:
        val = int(lm.group(1))
        lead = val * 7 if re.search(r"w", lm.group(0), re.I) else val

    is_quote = total is not None
    return ParsedQuote(
        is_quote=is_quote,
        material_cost=material,
        freight=freight,
        total=total,
        lead_days=lead,
        notes=None if is_quote else "No price detected (regex fallback).",
    )


def parse_quote(text: str) -> ParsedQuote:
    """Parse a supplier reply into structured terms. Never raises."""
    if not (text or "").strip():
        return ParsedQuote(is_quote=False, notes="Empty message.")
    parsed = _llm_parse(text)
    if parsed is not None:
        return parsed
    return _regex_parse(text)
