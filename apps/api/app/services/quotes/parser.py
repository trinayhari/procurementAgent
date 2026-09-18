"""Turn a supplier's reply (email body + attachment text) into a ParsedQuote.

Primary path: OpenAI Structured Outputs (same model/SDK as extraction). Fallback:
a regex pass that pulls the obvious dollar figures and a lead time, so ingest
still yields comparable numbers when no key is set or the model call fails.
"""
import re
from typing import List, Optional

from app.config import settings
from app.services import llm_health
from app.services.quotes.models import ParsedQuote, ParsedQuoteLine

_SYSTEM = (
    "You read construction supplier quotes and extract the commercial terms. "
    "Capture every priced line item (description, quantity, unit price, and the "
    "per-line lead time when stated). Return only numbers the supplier actually "
    "states; leave a field null if it is not clearly stated. Do NOT compute or sum "
    "subtotals, material totals, or grand totals yourself — leave material_cost and "
    "total null unless the supplier states them explicitly. Money is USD."
)

_MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")
_LEAD_RE = re.compile(r"(\d{1,3})\s*(?:business\s*)?(?:day|days|wk|wks|week|weeks)", re.I)
_TOTAL_HINT = re.compile(r"\b(grand\s+total|total|amount\s+due)\b", re.I)
_SUBTOTAL_HINT = re.compile(r"\b(sub\s*-?\s*total|material(?:s)?(?:\s+subtotal)?)\b", re.I)
_FREIGHT_HINT = re.compile(r"(freight|shipping|delivery\s+charge|delivery\s+fee|haul)", re.I)
# "$28.50/LF", "$1,240.00 each", "$95 per unit", "$18.50 / ft"
_UNIT_PRICE_RE = re.compile(
    r"\$\s?([\d,]+(?:\.\d{1,2})?)\s*(?:/\s*[A-Za-z]{1,6}\b|(?:each|ea|per\s+[A-Za-z]{1,8})\b)",
    re.I,
)
# "1,450 LF", "9 EA", "5 each", "3,400 SY", "2 tons"
_QTY_RE = re.compile(
    r"\b(\d[\d,]*(?:\.\d+)?)\s*(LF|LNFT|EA|EACH|SY|SF|CY|CF|TONS?|LBS?|GAL|FT|PCS?|PIECES?|BAGS?|ROLLS?|BOXES|BOX|UNITS?|SETS?|PAIRS?|BDL|BUNDLES?|PALLETS?|MBF|CWT)\b",
    re.I,
)
# Words a real quote carries; a promo/newsletter/invoice with a stray "$500"
# usually does not, so a bare dollar figure alone never makes a quote.
_QUOTE_SIGNAL = re.compile(
    r"\b(quot(?:e|ation|ed)|pricing|price[sd]?|bid|proposal|total|delivered|fob|lead\s*time|"
    r"each|per\s+(?:lf|ea|unit|ft|ton)|/\s*(?:lf|ea|ft|sy|cy|ton))\b",
    re.I,
)
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]+|\d+[.)])\s*")
# "5 EA x $3,150.00", "1,450 LF @ $28.50" — a quantity, a multiplier, a price.
_QTY_X_PRICE_RE = re.compile(
    r"\b(\d[\d,]*(?:\.\d+)?)\s*([A-Za-z]{1,7})\s*[x×@]\s*\$\s?([\d,]+(?:\.\d{1,2})?)",
    re.I,
)


def is_configured() -> bool:
    return bool(settings.openai_api_key)


def llm_status() -> dict:
    return llm_health.status()


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
        llm_health.record_success()
        return completion.choices[0].message.parsed
    except Exception as exc:
        llm_health.record_failure(exc, "quote parser")
        return None


def _money(m) -> Optional[float]:
    try:
        return float(m.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _line_name(line: str, cut_at: int) -> str:
    """The description part of a priced line: text before the quantity/price,
    minus bullets, trailing punctuation and a stray 'x' / '@'."""
    name = _BULLET_RE.sub("", line[:cut_at]).strip()
    name = re.sub(r"(?:\s*[,:;@\-–—]+|\s+[x×])*\s*$", "", name, flags=re.I).strip()
    return name


def _segments(line: str) -> List[str]:
    """One priced thing per segment: a line such as
    "DI pipe $19.00/LF, gate valve $400 each, freight $900" is three."""
    if len(_MONEY_RE.findall(line)) < 2:
        return [line]
    parts = [p.strip() for p in re.split(r"[;,]\s+", line) if p.strip()]
    return parts if len(parts) > 1 else [line]


def _regex_parse(text: str) -> ParsedQuote:
    """Deterministic fallback when no model is configured (or it fails).

    Reads what suppliers actually write: unit-priced lines ("1,450 LF @
    $28.50/LF", "9 EA @ $1,240.00 each") become line items with quantities so
    finalize_quote() can total them; an explicit subtotal / freight / total
    line is taken as stated; freight is never mistaken for the total. Only when
    the text names no lines or totals — just a figure and quote-like wording
    ("our price is $47,500 delivered") — is the largest figure used as the
    total. A stray dollar amount with no quote wording is not a quote.
    """
    lines: List[ParsedQuoteLine] = []
    total = freight = material = None
    candidates: List[float] = []

    segments: List[str] = []
    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if raw_line:
            segments.extend(_segments(raw_line))

    for line in segments:
        unit = _UNIT_PRICE_RE.search(line)
        if unit is None:
            qx = _QTY_X_PRICE_RE.search(line)
            if qx and _QTY_RE.match(qx.group(1) + " " + qx.group(2)):
                # Re-anchor on the price so the shared path below applies.
                unit = _MONEY_RE.search(line, qx.start(3) - 2)
        if unit and not _FREIGHT_HINT.search(line[: unit.start()]):
            qty_m = None
            for cand in _QTY_RE.finditer(line[: unit.start()]):
                # Skip a size that is really part of the description (8" pipe).
                if line[max(0, cand.start() - 1):cand.start()] in ('"', "'"):
                    continue
                qty_m = cand
            cut = qty_m.start() if qty_m else unit.start()
            name = _line_name(line, cut)
            if not name and qty_m:
                # "9 EA Gate valve @ $1,240 each" — description after the quantity.
                tail = line[qty_m.end():unit.start()]
                name = _line_name(tail, len(tail))
            if name:
                quantity = f"{qty_m.group(1)} {qty_m.group(2).upper()}" if qty_m else None
                extended = None
                trailing = [_money(m.group(1)) for m in _MONEY_RE.finditer(line[unit.end():])]
                if trailing and ("=" in line[unit.end():] or re.search(r"\bext", line, re.I)):
                    extended = trailing[-1]
                lines.append(ParsedQuoteLine(
                    name=name, quantity=quantity, unit_price=_money(unit.group(1)), extended=extended,
                ))
            continue
        amounts = [_money(m.group(1)) for m in _MONEY_RE.finditer(line)]
        amounts = [a for a in amounts if a is not None]
        if not amounts:
            continue
        if _FREIGHT_HINT.search(line):
            freight = amounts[-1]
        elif _SUBTOTAL_HINT.search(line) and not re.search(r"\bgrand\s+total\b", line, re.I):
            material = amounts[-1]
        elif _TOTAL_HINT.search(line):
            total = amounts[-1]
        else:
            candidates.extend(amounts)

    if total is None and material is None and not lines and candidates:
        if _QUOTE_SIGNAL.search(text):
            total = max(candidates)
    if material is None and total is not None and freight is not None and total > freight:
        material = round(total - freight, 2)

    lead = None
    lm = _LEAD_RE.search(text)
    if lm:
        val = int(lm.group(1))
        lead = val * 7 if re.search(r"w", lm.group(0), re.I) else val

    is_quote = total is not None or material is not None or bool(lines)
    return ParsedQuote(
        is_quote=is_quote,
        material_cost=material,
        freight=freight,
        total=total,
        lead_days=lead,
        line_items=lines,
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
