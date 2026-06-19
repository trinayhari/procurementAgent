"""Database accessors for the supplier directory + comms history."""
import json
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.supplier import Supplier, SupplierComm
from app.repositories import seed


def list_suppliers(db: Session) -> List[dict]:
    rows = db.scalars(select(Supplier).order_by(Supplier.seq)).all()
    return [s.to_dict() for s in rows]


def get_supplier(db: Session, supplier_id: str) -> Optional[dict]:
    row = db.get(Supplier, supplier_id)
    return row.to_dict() if row else None


def list_comms(db: Session) -> List[dict]:
    rows = db.scalars(select(SupplierComm).order_by(SupplierComm.seq)).all()
    return [c.to_dict() for c in rows]


def seed_suppliers(db: Session) -> None:
    """Populate the supplier directory + comms history once, on empty tables."""
    if not db.scalar(select(func.count()).select_from(Supplier)):
        for i, s in enumerate(seed.SUPPLIERS, start=1):
            db.add(
                Supplier(
                    seq=i,
                    id=s["id"],
                    name=s["name"],
                    cats=json.dumps(s.get("cats", [])),
                    contact=s.get("contact", ""),
                    phone=s.get("phone", ""),
                    email=s.get("email", ""),
                    web=s.get("web", ""),
                    rfq=s.get("rfq", ""),
                    rfq_tone=s.get("rfqTone", "gray"),
                    last=s.get("last", "—"),
                    quotes=s.get("quotes", "0"),
                    quote_val=s.get("quoteVal", "—"),
                    lead=s.get("lead", "—"),
                    logo=s.get("logo", "SU"),
                    logo_bg=s.get("logoBg", "#334155"),
                    fin=json.dumps(s.get("fin", {})),
                )
            )
    if not db.scalar(select(func.count()).select_from(SupplierComm)):
        for i, c in enumerate(seed.SUPPLIER_COMMS, start=1):
            db.add(
                SupplierComm(
                    seq=i,
                    tone=c.get("tone", "blue"),
                    title=c["title"],
                    body=c.get("body", ""),
                    time=c.get("time", ""),
                    icon=c.get("icon", "rfq"),
                )
            )
    db.commit()
