"""Database accessors for the supplier directory + comms history.

The directory is per-organization: each customer curates its own vendor list, so
every read and write filters on `org_id`. Comms history is per-supplier (each
row carries `supplier_id`) and is read only after the owning supplier has been
resolved within the caller's org.
"""
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


def list_suppliers(db: Session, org_id: str) -> List[dict]:
    rows = db.scalars(
        select(Supplier)
        .where(Supplier.organization_id == org_id)
        .order_by(Supplier.seq)
    ).all()
    return [s.to_dict() for s in rows]


def _get_row(db: Session, org_id: str, supplier_id: str) -> Optional[Supplier]:
    """The ORM row, or None when it doesn't exist *or* belongs to another org."""
    row = db.get(Supplier, supplier_id)
    return row if row is not None and row.organization_id == org_id else None


def get_supplier(db: Session, org_id: str, supplier_id: str) -> Optional[dict]:
    row = _get_row(db, org_id, supplier_id)
    return row.to_dict() if row else None


def find_by_name(db: Session, org_id: str, name: str) -> Optional[Supplier]:
    """This org's directory row whose name matches (case-insensitive), if any."""
    return db.scalars(
        select(Supplier).where(
            Supplier.organization_id == org_id,
            func.lower(Supplier.name) == name.strip().lower(),
        )
    ).first()


def _initials(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return "SU"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _unique_id(db: Session, name: str) -> str:
    # Deliberately unfiltered: `id` is the primary key, so it must be unique
    # across every organization, not just the caller's.
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "supplier"
    sid, n = base, 2
    while db.get(Supplier, sid) is not None:
        sid, n = f"{base}-{n}", n + 1
    return sid


def create_supplier(
    db: Session,
    org_id: str,
    *,
    name: str,
    contact: str = "",
    phone: str = "",
    email: str = "",
    web: str = "",
    cats: Optional[List[str]] = None,
) -> dict:
    """Add a supplier to this org's directory. Idempotent by name — returns the
    existing row if this supplier is already in the org's network."""
    existing = find_by_name(db, org_id, name)
    if existing is not None:
        return existing.to_dict()

    next_seq = (db.scalar(select(func.max(Supplier.seq))) or 0) + 1
    row = Supplier(
        organization_id=org_id,
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


def update_supplier(
    db: Session, org_id: str, supplier_id: str, fields: dict
) -> Optional[dict]:
    """Apply a partial edit to a directory supplier. `fields` holds only the keys
    the caller sent (from SupplierUpdate). Returns the updated row, or None if no
    supplier with that id exists in this org. The id is intentionally left
    unchanged even when the name changes, so existing references stay valid; the
    avatar initials track the new name."""
    row = _get_row(db, org_id, supplier_id)
    if row is None:
        return None
    if "name" in fields:
        row.name = fields["name"]
        row.logo = _initials(fields["name"])
    for key in ("contact", "phone", "email", "web"):
        if key in fields:
            setattr(row, key, fields[key] or "")
    if "cats" in fields:
        row.cats = json.dumps(fields["cats"] or [])
    db.commit()
    return row.to_dict()


def delete_supplier(db: Session, org_id: str, supplier_id: str) -> bool:
    """Remove a supplier from the org's directory. False if it didn't exist."""
    row = _get_row(db, org_id, supplier_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def list_comms(db: Session, supplier_id: str) -> List[dict]:
    """This supplier's communication history, oldest-slot-first by `seq`. Empty
    when the supplier has never been contacted. Callers validate org ownership of
    the supplier (via get_supplier) before reading its timeline."""
    rows = db.scalars(
        select(SupplierComm)
        .where(SupplierComm.supplier_id == supplier_id)
        .order_by(SupplierComm.seq)
    ).all()
    return [c.to_dict() for c in rows]


def seed_suppliers(db: Session, org_id: str) -> None:
    """Populate the supplier directory + comms history once, on empty tables."""
    if not db.scalar(select(func.count()).select_from(Supplier)):
        for i, s in enumerate(seed.SUPPLIERS, start=1):
            db.add(
                Supplier(
                    organization_id=org_id,
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
        for supplier_id, comms in seed.SUPPLIER_COMMS.items():
            for i, c in enumerate(comms, start=1):
                db.add(
                    SupplierComm(
                        supplier_id=supplier_id,
                        seq=i,
                        tone=c.get("tone", "blue"),
                        title=c["title"],
                        body=c.get("body", ""),
                        time=c.get("time", ""),
                        icon=c.get("icon", "rfq"),
                    )
                )
    db.commit()
