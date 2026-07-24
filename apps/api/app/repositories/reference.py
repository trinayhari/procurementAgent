"""Database accessors for prototype reference/display data.

Covers the dashboard, project workspace cards, vendor comparison, timeline, and
the demo RFQ inbox / quote list. All of it is seeded once from the literals in
seed.py (see ``seed_reference_data``) and then read back from the DB.
"""
import json
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.reference import (
    ActivityItem,
    Comparison,
    DashboardMetric,
    DemoQuote,
    DemoRfq,
    GanttBar,
    GanttColumn,
    Milestone,
    OverviewCard,
    PackageProgress,
    RfqFolder,
    SeedLineItemGroup,
)
from app.repositories import seed


# ---------------------------------------------------------------- read accessors
def get_dashboard(db: Session) -> dict:
    metrics = db.scalars(select(DashboardMetric).order_by(DashboardMetric.seq)).all()
    activity = db.scalars(select(ActivityItem).order_by(ActivityItem.seq)).all()
    return {
        "metrics": [m.to_dict() for m in metrics],
        "activity": [a.to_dict() for a in activity],
    }


def list_overview_cards(db: Session) -> List[dict]:
    rows = db.scalars(select(OverviewCard).order_by(OverviewCard.seq)).all()
    return [c.to_dict() for c in rows]


def list_packages(db: Session) -> List[dict]:
    rows = db.scalars(select(PackageProgress).order_by(PackageProgress.seq)).all()
    return [p.to_dict() for p in rows]


def list_line_item_groups(db: Session) -> List[dict]:
    rows = db.scalars(select(SeedLineItemGroup).order_by(SeedLineItemGroup.seq)).all()
    return [g.to_dict() for g in rows]


def get_comparison(db: Session, pkg: str) -> Optional[dict]:
    row = db.get(Comparison, pkg)
    return row.to_dict() if row else None


def get_timeline(db: Session) -> dict:
    milestones = db.scalars(select(Milestone).order_by(Milestone.seq)).all()
    gantt = db.scalars(select(GanttBar).order_by(GanttBar.seq)).all()
    cols = db.scalars(select(GanttColumn).order_by(GanttColumn.seq)).all()
    return {
        "milestones": [m.to_dict() for m in milestones],
        "gantt": [g.to_dict() for g in gantt],
        "ganttCols": [c.label for c in cols],
    }


def list_rfq_folders(db: Session) -> List[dict]:
    rows = db.scalars(select(RfqFolder).order_by(RfqFolder.seq)).all()
    return [f.to_dict() for f in rows]


def list_demo_rfqs(db: Session) -> List[dict]:
    rows = db.scalars(select(DemoRfq).order_by(DemoRfq.seq)).all()
    return [r.to_dict() for r in rows]


def get_demo_rfq(db: Session, rfq_id: str) -> Optional[DemoRfq]:
    return db.get(DemoRfq, rfq_id)


def list_demo_quotes(db: Session) -> List[dict]:
    rows = db.scalars(select(DemoQuote).order_by(DemoQuote.seq)).all()
    return [q.to_dict() for q in rows]


def get_demo_quote(db: Session, quote_id: str) -> Optional[dict]:
    row = db.get(DemoQuote, quote_id)
    return row.to_dict() if row else None


# ---------------------------------------------------------------------- seeding
def _seed_if_empty(db: Session, model, rows) -> None:
    if db.scalar(select(func.count()).select_from(model)):
        return
    for row in rows:
        db.add(row)


def seed_reference_data(db: Session) -> None:
    """Seed all reference tables from the seed.py literals, idempotently."""
    _seed_if_empty(db, DashboardMetric, [
        DashboardMetric(
            seq=i, label=m["label"], value=m["value"], delta=m.get("delta", ""),
            sub=m.get("sub", ""), up=m.get("up", False), down=m.get("down", False),
            ai=m.get("ai", False), risk=m.get("risk", False),
        )
        for i, m in enumerate(seed.METRICS, start=1)
    ])

    _seed_if_empty(db, ActivityItem, [
        ActivityItem(
            seq=i, icon=a["icon"], tone=a.get("tone", "blue"), title=a["title"],
            meta=a.get("meta", ""), time=a.get("time", ""),
        )
        for i, a in enumerate(seed.ACTIVITY, start=1)
    ])

    _seed_if_empty(db, OverviewCard, [
        OverviewCard(
            seq=i, label=c["label"], value=c["value"], sub=c.get("sub", ""),
            icon=c.get("icon", "file"), tone=c.get("tone", "blue"), ai=c.get("ai", False),
        )
        for i, c in enumerate(seed.OVERVIEW_CARDS, start=1)
    ])

    _seed_if_empty(db, PackageProgress, [
        PackageProgress(seq=i, name=p["name"], pct=p["pct"], tone=p.get("tone", "blue"))
        for i, p in enumerate(seed.PACKAGES, start=1)
    ])

    _seed_if_empty(db, SeedLineItemGroup, [
        SeedLineItemGroup(
            seq=i, group=g["group"], count=g["count"], tone=g.get("tone", "blue"),
            items=json.dumps(g.get("items", [])),
        )
        for i, g in enumerate(seed.LINE_ITEMS, start=1)
    ])

    _seed_if_empty(db, Comparison, [
        Comparison(
            pkg=pkg,
            suppliers=json.dumps(c.get("suppliers", [])),
            rows=json.dumps(c.get("rows", [])),
            recommendation=c.get("recommendation", ""),
            reasons=json.dumps(c.get("reasons", [])),
            savings=c.get("savings", ""),
            savings_note=c.get("savingsNote", ""),
        )
        for pkg, c in seed.COMPARISONS.items()
    ])

    _seed_if_empty(db, Milestone, [
        Milestone(
            seq=i, name=m["name"], date=m.get("date", ""), status=m.get("status", "Upcoming"),
            desc=m.get("desc", ""), tone=m.get("tone", "gray"), done=m.get("done", False),
            active=m.get("active", False),
        )
        for i, m in enumerate(seed.MILESTONES, start=1)
    ])

    _seed_if_empty(db, GanttBar, [
        GanttBar(
            seq=i, name=g["name"], start=g["start"], length=g["len"],
            tone=g.get("tone", "blue"), label=g.get("label", ""), warn=g.get("warn", False),
        )
        for i, g in enumerate(seed.GANTT, start=1)
    ])

    _seed_if_empty(db, GanttColumn, [
        GanttColumn(seq=i, label=label)
        for i, label in enumerate(seed.GANTT_COLS, start=1)
    ])

    _seed_if_empty(db, RfqFolder, [
        RfqFolder(seq=i, name=f["name"], count=f["count"])
        for i, f in enumerate(seed.RFQ_FOLDERS, start=1)
    ])

    _seed_if_empty(db, DemoRfq, [
        DemoRfq(
            seq=i, id=r["id"], sup=r["sup"], pkg=r["pkg"], folder=r.get("folder", "Draft"),
            status=r.get("status", "Draft"), status_tone=r.get("statusTone", "gray"),
            preview=r.get("preview", ""), time=r.get("time", "—"), unread=r.get("unread", False),
            logo=r.get("logo", "RF"), logo_bg=r.get("logoBg", "#334155"),
            thread=json.dumps(seed._thread_for(r)),
        )
        for i, r in enumerate(seed.RFQS, start=1)
    ])

    _seed_if_empty(db, DemoQuote, [
        DemoQuote(
            seq=i, id=q["id"], sup=q["sup"], pkg=q["pkg"], amount=q.get("amount", "—"),
            freight=q.get("freight", "—"), total=q.get("total", "—"), lead=q.get("lead", "—"),
            date=q.get("date", "—"), logo=q.get("logo", "SU"), logo_bg=q.get("logoBg", "#334155"),
            best=q.get("best", False),
        )
        for i, q in enumerate(seed.QUOTES, start=1)
    ])

    db.commit()
