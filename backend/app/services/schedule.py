"""Build a project schedule from extracted timeline events.

Turns the flat `timeline_events` rows (see app/models/timeline_event.py) into
the `Timeline` shape the frontend already renders:
  • events with a start AND end date become Gantt bars, positioned as PERCENT
    of the overall span (the frontend renders `start`/`len` as CSS percentages),
    with month/quarter labels as the column headers;
  • point-in-time events (one date) become the milestone list, with done/active
    computed against today;
  • events with only relative wording ('Week 3-8', '60 days after NTP') can't be
    placed on a calendar — they are listed as unscheduled milestones showing the
    document's own wording.

Returns None when there are no events, so the route can fall back to the demo
timeline (only present when demo seeding is on).
"""
import calendar
from datetime import date
from typing import List, Optional

_BAR_TONES = ["blue", "violet", "success", "warn", "ai"]


def _parse(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _display(d: date, with_year: bool = True) -> str:
    return f"{d.strftime('%b')} {d.day}, {d.year}" if with_year else f"{d.strftime('%b')} {d.day}"


def _provenance(e: dict) -> str:
    desc = e.get("desc", "")
    src = e.get("source_doc", "")
    frm = f"From {src}" if src else ""
    return f"{desc} · {frm}" if desc and frm else (desc or frm)


def _dedup(events: List[dict]) -> List[dict]:
    """Drop repeats of the same event name across documents (e.g. the contract
    and the schedule both list 'Substantial Completion'), preferring the entry
    that carries a calendar date."""
    by_name = {}
    order = []
    for e in events:
        key = e["name"].strip().lower()
        if key not in by_name:
            by_name[key] = e
            order.append(key)
        elif e.get("start") and not by_name[key].get("start"):
            by_name[key] = e
    return [by_name[k] for k in order]


def _month_add(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


def _build_columns(span_start: date, span_end: date) -> List[str]:
    """Month labels across the span; quarters past ~14 months, years past ~4 years."""
    months = (span_end.year - span_start.year) * 12 + (span_end.month - span_start.month) + 1
    one_year = span_start.year == span_end.year
    if months <= 14:
        cur = date(span_start.year, span_start.month, 1)
        cols = []
        for _ in range(months):
            cols.append(cur.strftime("%b") if one_year else f"{cur.strftime('%b')} '{cur.year % 100:02d}")
            cur = _month_add(cur, 1)
        return cols
    quarters = (months + 2) // 3
    if quarters <= 16:
        cols = []
        cur = date(span_start.year, span_start.month, 1)
        for _ in range(quarters):
            q = (cur.month - 1) // 3 + 1
            cols.append(f"Q{q} '{cur.year % 100:02d}")
            cur = _month_add(cur, 3)
        return cols
    return [str(y) for y in range(span_start.year, span_end.year + 1)]


def _build_gantt(ranged: List[dict], today: date) -> dict:
    """Percent-positioned bars over a span padded to whole-month boundaries."""
    ranged = sorted(ranged, key=lambda e: e["_start"])
    first = min(e["_start"] for e in ranged)
    last = max(e["_end"] for e in ranged)
    span_start = date(first.year, first.month, 1)
    span_end = date(last.year, last.month, calendar.monthrange(last.year, last.month)[1])
    total_days = max((span_end - span_start).days + 1, 1)
    one_year = span_start.year == span_end.year

    bars = []
    for i, e in enumerate(ranged):
        start_pct = round((e["_start"] - span_start).days / total_days * 100)
        len_pct = max(round(((e["_end"] - e["_start"]).days + 1) / total_days * 100), 2)
        len_pct = min(len_pct, 100 - start_pct)
        bars.append({
            "name": e["name"],
            "start": start_pct,
            "len": len_pct,
            "tone": _BAR_TONES[i % len(_BAR_TONES)],
            "label": f"{_display(e['_start'], not one_year)} – {_display(e['_end'], not one_year)}",
            "warn": False,
        })
    return {"gantt": bars, "ganttCols": _build_columns(span_start, span_end)}


def _build_milestones(points: List[dict], undated: List[dict], today: date) -> List[dict]:
    points = sorted(points, key=lambda e: e["_start"])
    out = []
    for e in points:
        done = e["_start"] < today
        out.append({
            "name": e["name"],
            "date": _display(e["_start"]),
            "status": "Complete" if done else "Upcoming",
            "desc": _provenance(e),
            "tone": "success" if done else "gray",
            "done": done,
            "active": False,
        })
    # The next upcoming milestone is the one the project is working toward.
    for m in out:
        if not m["done"]:
            m["active"] = True
            m["tone"] = "blue"
            break
    for e in undated:
        out.append({
            "name": e["name"],
            "date": e.get("date_text", "") or "—",
            "status": "Unscheduled",
            "desc": _provenance(e),
            "tone": "gray",
            "done": False,
            "active": False,
        })
    return out


def build_schedule(events: List[dict], today: Optional[date] = None) -> Optional[dict]:
    """The project's Timeline (milestones + gantt) from its extracted events,
    or None when nothing has been extracted yet."""
    if not events:
        return None
    today = today or date.today()

    ranged, points, undated = [], [], []
    for e in _dedup(events):
        start, end = _parse(e.get("start", "")), _parse(e.get("end", ""))
        if start and end and end > start:
            ranged.append({**e, "_start": start, "_end": end})
        elif start:
            points.append({**e, "_start": start})
        else:
            undated.append(e)

    gantt = _build_gantt(ranged, today) if ranged else {"gantt": [], "ganttCols": []}
    return {
        "milestones": _build_milestones(points, undated, today),
        "gantt": gantt["gantt"],
        "ganttCols": gantt["ganttCols"],
    }
