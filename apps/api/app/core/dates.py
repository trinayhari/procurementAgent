"""Need-by dates: stored as ISO `YYYY-MM-DD` strings, shown as words.

A project's need-by is the date the material has to be on site (the PM's
"pour is the 21st"); an RFQ inherits it so suppliers, follow-ups and the
award card all quote the same date.
"""
from datetime import date
from typing import Optional


def parse_iso_date(value: Optional[str]) -> Optional[str]:
    """Normalise a `YYYY-MM-DD` string; None for blank. Raises ValueError
    for anything else so schema validators can report it."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("Need-by must be a date like 2026-10-14") from exc


def humanize(iso: Optional[str]) -> str:
    """'2026-10-14' -> 'October 14, 2026'; the input unchanged if it is not ISO."""
    if not iso:
        return ""
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.strftime('%B')} {d.day}, {d.year}"
