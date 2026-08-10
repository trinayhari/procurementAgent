from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories import suppliers as suppliers_repo
from app.schemas.supplier import (
    Supplier,
    SupplierCreate,
    SupplierDetail,
    SupplierUpdate,
)

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("", response_model=List[Supplier])
def list_suppliers(db: Session = Depends(get_db)):
    return suppliers_repo.list_suppliers(db)


@router.post("", response_model=Supplier, status_code=201)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)):
    """Add a supplier to the customer's directory (manually or from a search
    result). Idempotent by name."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Supplier name is required")
    return suppliers_repo.create_supplier(
        db,
        name=name,
        contact=payload.contact,
        phone=payload.phone,
        email=payload.email,
        web=payload.web,
        cats=payload.cats,
    )


@router.get("/{supplier_id}", response_model=SupplierDetail)
def get_supplier(supplier_id: str, db: Session = Depends(get_db)):
    supplier = suppliers_repo.get_supplier(db, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {**supplier, "comms": suppliers_repo.list_comms(db, supplier_id)}


@router.patch("/{supplier_id}", response_model=Supplier)
def update_supplier(
    supplier_id: str, payload: SupplierUpdate, db: Session = Depends(get_db)
):
    """Edit a supplier's details in the customer's directory. Only the fields
    present in the request body are changed."""
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Supplier name is required")
        clash = suppliers_repo.find_by_name(db, name)
        if clash is not None and clash.id != supplier_id:
            raise HTTPException(
                status_code=409, detail="Another supplier already has that name"
            )
        fields["name"] = name
    updated = suppliers_repo.update_supplier(db, supplier_id, fields)
    if updated is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return updated


@router.delete("/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: str, db: Session = Depends(get_db)):
    """Remove a supplier from the customer's network."""
    if not suppliers_repo.delete_supplier(db, supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
