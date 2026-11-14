from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from ..db import Db, get_db
from ..deps import require_admin
from ..repos import admin_payments, dashboards
from ..schemas import RejectIn

router = APIRouter(prefix="/admin", tags=["admin"])
Admin = Annotated[dict, Depends(require_admin)]
DbDep = Annotated[Db, Depends(get_db)]


@router.get("/dashboard")
def dashboard(_admin: Admin, db: DbDep):
    return dashboards.admin_dashboard(db)


@router.get("/payments")
def payments(_admin: Admin, db: DbDep, status: Literal["pending", "confirmed", "rejected"] | None = None,
             limit: Annotated[int, Query(ge=1, le=500)] = 200):
    return admin_payments.list_payments(db, status, limit)


@router.get("/payments/{payment_id}")
def payment(payment_id: int, _admin: Admin, db: DbDep):
    return admin_payments.get_payment(db, payment_id)


@router.post("/payments/{payment_id}/confirm")
def confirm(payment_id: int, admin: Admin, db: DbDep):
    return admin_payments.confirm_payment(db, payment_id, admin["id"])


@router.post("/payments/{payment_id}/reject")
def reject(payment_id: int, body: RejectIn, admin: Admin, db: DbDep):
    return admin_payments.reject_payment(db, payment_id, admin["id"], body.reason)
