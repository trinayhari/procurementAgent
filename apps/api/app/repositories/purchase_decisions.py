"""Database accessors for purchase decisions (package awards)."""
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.purchase_decision import PurchaseDecision


def add_decision(
    db: Session,
    org_id: str,
    project_id: str,
    package: str,
    package_label: str,
    summary: dict,
    selections: dict,
    strategy: Optional[str],
    decided_by,
    po_numbers: Optional[List[dict]] = None,
) -> PurchaseDecision:
    """Stage a decision row on the session WITHOUT committing — the caller
    commits it together with the quote status flips so the award is atomic.

    `decided_by` is anything with `.id` and `.email` (a User, or the award
    service's Actor for an approval-link decision)."""
    row = PurchaseDecision(
        organization_id=org_id,
        id=uuid.uuid4().hex,
        project_id=project_id,
        package=package,
        package_label=package_label,
        strategy=strategy,
        selections=json.dumps(selections),
        supplier_ids=json.dumps(sorted(summary.get("supplierIds") or [])),
        suppliers=json.dumps(list(summary.get("suppliers") or [])),
        total=float(summary.get("total") or 0),
        material=float(summary.get("material") or 0),
        freight=float(summary.get("freight") or 0),
        lead_days=summary.get("leadDays"),
        po_count=int(summary.get("poCount") or 0),
        po_numbers=json.dumps(po_numbers or []),
        decided_by=decided_by.id if decided_by else "system",
        decided_by_email=decided_by.email if decided_by else "system",
        # Microsecond precision so two awards in the same second (an immediate
        # supersede) still order deterministically — SQLite's CURRENT_TIMESTAMP
        # default is whole seconds.
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    return row


def mark_superseded(db: Session, org_id: str, decision_id: str, by_id: str) -> None:
    """Flag an earlier award as replaced by `by_id` (staged on the session; the
    caller's commit makes the re-award atomic)."""
    row = db.get(PurchaseDecision, decision_id)
    if row is None or row.organization_id != org_id:
        return
    row.status = "superseded"
    row.superseded_by = by_id


def superseded_by_decision(db: Session, org_id: str, decision_id: str) -> Optional[dict]:
    """The earlier award that `decision_id` replaced, if any."""
    row = db.scalars(
        select(PurchaseDecision).where(
            PurchaseDecision.organization_id == org_id,
            PurchaseDecision.superseded_by == decision_id,
        ).order_by(PurchaseDecision.created_at.desc())
    ).first()
    return row.to_dict() if row else None


def set_notifications(db: Session, org_id: str, decision_id: str, outcome: dict) -> None:
    """Store the supplier-notification outcome for an award (see award_notify)."""
    row = db.get(PurchaseDecision, decision_id)
    if row is None or row.organization_id != org_id:
        return
    row.notifications = json.dumps(outcome)
    db.commit()


def list_for_project(db: Session, org_id: str, project_id: str) -> List[dict]:
    rows = db.scalars(
        select(PurchaseDecision)
        .where(
            PurchaseDecision.organization_id == org_id,
            PurchaseDecision.project_id == project_id,
        )
        .order_by(PurchaseDecision.created_at.desc())
    ).all()
    return [r.to_dict() for r in rows]


def latest_for_package(
    db: Session, org_id: str, project_id: str, package: str
) -> Optional[dict]:
    """The most recent award for one package on a project, or None."""
    row = db.scalars(
        select(PurchaseDecision)
        .where(
            PurchaseDecision.organization_id == org_id,
            PurchaseDecision.project_id == project_id,
            PurchaseDecision.package == package,
        )
        # The live decision first (a superseded one never outranks it, even
        # when timestamps tie), then newest.
        .order_by(
            (PurchaseDecision.status == "superseded").asc(),
            PurchaseDecision.created_at.desc(),
        )
    ).first()
    return row.to_dict() if row else None
