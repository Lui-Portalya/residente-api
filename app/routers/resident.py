from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import Db, get_db
from ..deps import require_resident
from ..errors import NotFound
from ..repos import billing, dashboards, reservations
from ..schemas import CancelIn, ReservationIn
from ..timeutil import is_date, local_now, today

router = APIRouter(prefix="/resident", tags=["resident"])
Resident = Annotated[dict, Depends(require_resident)]
DbDep = Annotated[Db, Depends(get_db)]


@router.get("/dashboard")
def dashboard(user: Resident, db: DbDep):
    return dashboards.resident_dashboard(db, user)


# ---- Payments (read-only) ----


@router.get("/charges")
def charges(user: Resident, db: DbDep, status: Literal["pending", "paid"] | None = None):
    return billing.list_charges(db, user["residence"]["id"], status)


@router.get("/payments")
def payments(user: Resident, db: DbDep, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return billing.list_payments(db, user["residence"]["id"], limit)


# ---- Common areas ----


@router.get("/areas")
def areas(user: Resident, db: DbDep):
    now, rid = local_now(), user["residence"]["id"]
    out = []
    for a in reservations.list_areas(db):
        usage = reservations.residence_usage(db, a["id"], rid, now[:7], now)
        out.append({
            "id": a["id"], "name": a["name"], "description": a["description"], "capacity": a["capacity"],
            "open_time": a["open_time"], "close_time": a["close_time"], "slot_minutes": a["slot_minutes"],
            "fee_cents": a["fee_cents"], "deposit_cents": a["deposit_cents"], "requires_approval": bool(a["requires_approval"]),
            "advance_days": a["advance_days"], "cancel_cutoff_hours": a["cancel_cutoff_hours"], "rules": a["rules"],
            "limits": {"max_active": a["max_active_per_residence"], "max_per_month": a["max_per_month_per_residence"]},
            "usage": {"active": usage["active"], "this_month": usage["in_month"]},
        })
    return out


@router.get("/areas/{area_id}/availability")
def area_availability(
    area_id: int, user: Resident, db: DbDep,
    from_: Annotated[str | None, Query(alias="from", description="YYYY-MM-DD, default today")] = None,
    days: Annotated[int, Query(ge=1, le=31)] = 7,
):
    area = reservations.get_area(db, area_id)
    if not area or not area["active"]:
        raise NotFound("Area not found.")
    start = from_ or today()
    if not is_date(start):
        raise HTTPException(422, "`from` must be YYYY-MM-DD.")
    return {"area_id": area_id, "days": reservations.availability(db, area, user["residence"]["id"], start, days)}


# ---- Reservations ----


@router.get("/reservations")
def my_reservations(user: Resident, db: DbDep, scope: Literal["upcoming", "history"] = "upcoming"):
    now, rid = local_now(), user["residence"]["id"]
    rows = reservations.list_upcoming(db, rid, now) if scope == "upcoming" else reservations.list_history(db, rid, now)
    return [reservations.present(r, now) for r in rows]


@router.post("/reservations", status_code=201)
def book(body: ReservationIn, user: Resident, db: DbDep):
    made = reservations.create_reservation(
        db, area_id=body.area_id, residence_id=user["residence"]["id"], user_id=user["id"],
        date=body.date, start=body.start, note=body.note,
    )
    row = reservations.get_reservation(db, made["id"])
    return reservations.present(row, local_now())  # type: ignore[arg-type]


@router.post("/reservations/{reservation_id}/cancel")
def cancel(reservation_id: int, user: Resident, db: DbDep, body: CancelIn | None = None):
    reservations.cancel_reservation(
        db, reservation_id, residence_id=user["residence"]["id"], user_id=user["id"], reason=body.reason if body else "",
    )
    row = reservations.get_reservation(db, reservation_id)
    return reservations.present(row, local_now())  # type: ignore[arg-type]
