"""Database accessors for purchase decisions (package awards)."""
import json
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.purchase_decision import PurchaseDecision
from app.models.user import User


def add_decision(
    db: Session,
    project_id: str,
    package: str,
    package_label: str,
    summary: dict,
    selections: dict,
    strategy: Optional[str],
    decided_by: Optional[User],
) -> PurchaseDecision:
    """Stage a decision row on the session WITHOUT committing — the caller
    commits it together with the quote status flips so the award is atomic."""
    row = PurchaseDecision(
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
        decided_by=decided_by.id if decided_by else "system",
        decided_by_email=decided_by.email if decided_by else "system",
    )
    db.add(row)
    return row


def list_for_project(db: Session, project_id: str) -> List[dict]:
    rows = db.scalars(
        select(PurchaseDecision)
        .where(PurchaseDecision.project_id == project_id)
        .order_by(PurchaseDecision.created_at.desc())
    ).all()
    return [r.to_dict() for r in rows]
