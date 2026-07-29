from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.user import User
from app.repositories import suppliers as suppliers_repo
from app.schemas.supplier import Supplier, SupplierCreate, SupplierDetail

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("", response_model=List[Supplier])
def list_suppliers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return suppliers_repo.list_suppliers(db, current_user.organization_id)


@router.post("", response_model=Supplier, status_code=201)
def create_supplier(
    payload: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a supplier to the customer's directory (manually or from a search
    result). Idempotent by name within the organization."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Supplier name is required")
    return suppliers_repo.create_supplier(
        db,
        current_user.organization_id,
        name=name,
        contact=payload.contact,
        phone=payload.phone,
        email=payload.email,
        web=payload.web,
        cats=payload.cats,
    )


@router.get("/{supplier_id}", response_model=SupplierDetail)
def get_supplier(
    supplier_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    supplier = suppliers_repo.get_supplier(db, current_user.organization_id, supplier_id)
    if supplier is None:
        # 404 (not 403) for another org's supplier — a 403 confirms it exists.
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {**supplier, "comms": suppliers_repo.list_comms(db)}


@router.delete("/{supplier_id}", status_code=204)
def delete_supplier(
    supplier_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a supplier from the customer's network."""
    if not suppliers_repo.delete_supplier(db, current_user.organization_id, supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
