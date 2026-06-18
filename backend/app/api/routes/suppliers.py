from typing import List

from fastapi import APIRouter, HTTPException

from app.repositories import seed
from app.schemas.supplier import Supplier, SupplierDetail

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("", response_model=List[Supplier])
def list_suppliers():
    return seed.SUPPLIERS


@router.get("/{supplier_id}", response_model=SupplierDetail)
def get_supplier(supplier_id: str):
    supplier = seed.get_supplier(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {**supplier, "comms": seed.SUPPLIER_COMMS}
