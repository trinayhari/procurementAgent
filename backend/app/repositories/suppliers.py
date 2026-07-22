"""Database accessors for the supplier directory + comms history."""
import json
import re
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.supplier import Supplier, SupplierComm
from app.repositories import seed

# Avatar background palette for newly-added suppliers (seeded rows carry their own).
_LOGO_PALETTE = [
    "#0a4d8c", "#16a34a", "#0f766e", "#b45309",
    "#7c3aed", "#be123c", "#2563eb", "#334155",
]


def list_suppliers(db: Session) -> List[dict]:
    rows = db.scalars(select(Supplier).order_by(Supplier.seq)).all()
    return [s.to_dict() for s in rows]


def get_supplier(db: Session, supplier_id: str) -> Optional[dict]:
    row = db.get(Supplier, supplier_id)
    return row.to_dict() if row else None


def find_by_name(db: Session, name: str) -> Optional[Supplier]:
    """The directory row whose name matches (case-insensitive), if any."""
    return db.scalars(
        select(Supplier).where(func.lower(Supplier.name) == name.strip().lower())
    ).first()


def _initials(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return "SU"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _unique_id(db: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "supplier"
    sid, n = base, 2
    while db.get(Supplier, sid) is not None:
        sid, n = f"{base}-{n}", n + 1
    return sid


def create_supplier(
    db: Session,
    *,
    name: str,
    contact: str = "",
    phone: str = "",
    email: str = "",
    web: str = "",
    cats: Optional[List[str]] = None,
) -> dict:
    """Add a supplier to the directory. Idempotent by name — returns the existing
    row if this supplier is already in the network."""
    existing = find_by_name(db, name)
    if existing is not None:
        return existing.to_dict()

    next_seq = (db.scalar(select(func.max(Supplier.seq))) or 0) + 1
    row = Supplier(
        seq=next_seq,
        id=_unique_id(db, name),
        name=name.strip(),
        cats=json.dumps(cats or []),
        contact=contact or "",
        phone=phone or "",
        email=email or "",
        web=web or "",
        rfq="New",
        rfq_tone="gray",
        last="—",
        quotes="0",
        quote_val="—",
        lead="—",
        logo=_initials(name),
        logo_bg=_LOGO_PALETTE[next_seq % len(_LOGO_PALETTE)],
        fin=json.dumps({"submitted": "0", "total": "—", "avg": "—"}),
    )
    db.add(row)
    db.commit()
    return row.to_dict()


def delete_supplier(db: Session, supplier_id: str) -> bool:
    """Remove a supplier from the directory. Returns False if it didn't exist."""
    row = db.get(Supplier, supplier_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


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
