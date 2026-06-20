from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories import suppliers as suppliers_repo
from app.schemas.supplier import Supplier, SupplierDetail

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("", response_model=List[Supplier])
def list_suppliers(db: Session = Depends(get_db)):
    return suppliers_repo.list_suppliers(db)


@router.get("/{supplier_id}", response_model=SupplierDetail)
def get_supplier(supplier_id: str, db: Session = Depends(get_db)):
    supplier = suppliers_repo.get_supplier(db, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {**supplier, "comms": suppliers_repo.list_comms(db)}
