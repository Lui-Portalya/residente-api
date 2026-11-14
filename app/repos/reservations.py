"""Common-area bookings (resident side), ported from repos/reservations.ts and repos/areas.ts."""
from ..db import Db, all_, one, tx
from ..errors import DomainError, NotFound
from ..timeutil import add_days, from_minutes, is_date, local_now, shift_hours, to_minutes

# ---------- Areas ----------


def list_areas(db: Db, only_active: bool = True) -> list[dict]:
    return all_(db, f"SELECT * FROM common_areas {'WHERE active = 1' if only_active else ''} ORDER BY name")


def get_area(db: Db, area_id: int) -> dict | None:
    return one(db, "SELECT * FROM common_areas WHERE id = ?", (area_id,))


# ---------- Reservation rows ----------

SELECT = """SELECT v.id, v.common_area_id, a.name AS area_name, v.residence_id, r.code AS residence_code, v.user_id, u.name AS user_name,
  v.start_at, v.end_at, v.status, v.note, v.decided_at, du.name AS decided_by_name, v.decision_note, v.cancelled_at, v.cancel_reason,
  v.deposit_status, v.deposit_retained_cents, v.deposit_note, v.deposit_settled_at, v.created_at, a.cancel_cutoff_hours,
  a.fee_cents AS area_fee_cents, a.deposit_cents AS area_deposit_cents,
  f.id AS fee_charge_id, f.amount_cents AS fee_cents, f.status AS fee_status,
  COALESCE((SELECT SUM(p.amount_cents) FROM payments p WHERE p.charge_id = f.id AND p.status != 'rejected'), 0) AS fee_paid_cents,
  d.id AS deposit_charge_id, d.amount_cents AS deposit_cents, d.status AS deposit_charge_status,
  COALESCE((SELECT SUM(p.amount_cents) FROM payments p WHERE p.charge_id = d.id AND p.status != 'rejected'), 0) AS deposit_paid_cents
  FROM reservations v
  JOIN common_areas a ON a.id = v.common_area_id
  JOIN residences r ON r.id = v.residence_id
  JOIN users u ON u.id = v.user_id
  LEFT JOIN users du ON du.id = v.decided_by
  LEFT JOIN charges f ON f.reservation_id = v.id AND f.type = 'common_area'
  LEFT JOIN charges d ON d.reservation_id = v.id AND d.type = 'deposit'"""


def deposit_state(r: dict) -> str:
    """Where the deposit stands, derived from the charge and the settlement fields."""
    if r["deposit_charge_id"] is None:
        return "none"
    if r["deposit_status"]:
        return r["deposit_status"]
    if r["deposit_charge_status"] == "void":
        return "voided"
    if r["deposit_charge_status"] == "paid":
        return "held"
    paid = r["deposit_paid_cents"]
    return "under_review" if paid >= (r["deposit_cents"] or 0) and paid > 0 else "due"


def cancel_deadline(r: dict) -> str:
    return shift_hours(r["start_at"], -r["cancel_cutoff_hours"])[:16]


def resident_can_cancel(r: dict, now: str) -> tuple[bool, str | None]:
    if r["status"] in ("cancelled", "rejected"):
        return False, "This booking is no longer active."
    if r["start_at"] <= now:
        return False, "Past bookings cannot be cancelled."
    if r["status"] == "pending":
        return True, None  # a request can always be withdrawn
    if r["cancel_cutoff_hours"] > 0 and now > cancel_deadline(r):
        return False, (f"Cancellations close {r['cancel_cutoff_hours']} hours before the start "
                       f"({cancel_deadline(r).replace('T', ' ')}). Contact the administration.")
    return True, None


def present(r: dict, now: str) -> dict:
    """A reservation row as the API returns it, with derived cancellation and deposit info."""
    ok, why = resident_can_cancel(r, now)
    return {
        "id": r["id"], "area_id": r["common_area_id"], "area_name": r["area_name"],
        "start_at": r["start_at"], "end_at": r["end_at"], "status": r["status"], "note": r["note"],
        "decision_note": r["decision_note"], "cancel_reason": r["cancel_reason"], "created_at": r["created_at"],
        "fee": {"charge_id": r["fee_charge_id"], "amount_cents": r["fee_cents"], "status": r["fee_status"], "paid_cents": r["fee_paid_cents"]}
        if r["fee_charge_id"] else None,
        "deposit": {"charge_id": r["deposit_charge_id"], "amount_cents": r["deposit_cents"], "state": deposit_state(r),
                    "paid_cents": r["deposit_paid_cents"], "retained_cents": r["deposit_retained_cents"]}
        if r["deposit_charge_id"] else None,
        "can_cancel": ok, "cancel_blocked_reason": why,
        "cancel_deadline": cancel_deadline(r) if r["status"] == "confirmed" and r["cancel_cutoff_hours"] > 0 else None,
    }


def get_reservation(db: Db, reservation_id: int) -> dict | None:
    return one(db, f"{SELECT} WHERE v.id = ?", (reservation_id,))


def list_upcoming(db: Db, residence_id: int, now: str | None = None, limit: int = 50) -> list[dict]:
    now = now or local_now()
    return all_(
        db,
        f"{SELECT} WHERE v.status IN ('pending', 'confirmed') AND v.end_at > ? AND v.residence_id = ? ORDER BY v.start_at LIMIT ?",
        (now, residence_id, limit),
    )


def list_history(db: Db, residence_id: int, now: str | None = None, limit: int = 20) -> list[dict]:
    now = now or local_now()
    return all_(
        db,
        f"{SELECT} WHERE v.residence_id = ? AND (v.status IN ('cancelled', 'rejected') OR v.end_at <= ?) ORDER BY v.start_at DESC LIMIT ?",
        (residence_id, now, limit),
    )


# ---------- Blackouts and limits ----------


def blackout_for(db: Db, area_id: int, date: str) -> dict | None:
    return one(
        db,
        """SELECT b.id, b.common_area_id, b.start_date, b.end_date, b.reason FROM area_blackouts b
           WHERE (b.common_area_id = ? OR b.common_area_id IS NULL) AND b.start_date <= ? AND b.end_date >= ?
           ORDER BY b.common_area_id IS NULL, b.id LIMIT 1""",
        (area_id, date, date),
    )


def residence_usage(db: Db, area_id: int, residence_id: int, month: str, now: str) -> dict:
    return one(
        db,
        """SELECT COALESCE(SUM(CASE WHEN end_at > ? THEN 1 ELSE 0 END), 0) AS active,
                  COALESCE(SUM(CASE WHEN substr(start_at, 1, 7) = ? THEN 1 ELSE 0 END), 0) AS in_month
           FROM reservations WHERE common_area_id = ? AND residence_id = ? AND status IN ('pending', 'confirmed')""",
        (now, month, area_id, residence_id),
    )  # type: ignore[return-value]


def booking_restriction(db: Db, area: dict, residence_id: int, date: str, now: str) -> str | None:
    """Why a residence cannot book the area on that date right now (limits and blackouts), or None if it can."""
    name = area["name"]
    blackout = blackout_for(db, area["id"], date)
    if blackout:
        return f"{name} is not available on this date{': ' + blackout['reason'] if blackout['reason'] else ''}."
    if area["advance_days"] > 0 and date > add_days(now[:10], area["advance_days"]):
        return f"{name} can be booked up to {area['advance_days']} days ahead."
    usage = residence_usage(db, area["id"], residence_id, date[:7], now)
    mx = area["max_active_per_residence"]
    if mx > 0 and usage["active"] >= mx:
        n = usage["active"]
        return f"Your residence already holds {n} upcoming booking{'' if n == 1 else 's'} of {name} (limit {mx})."
    mm = area["max_per_month_per_residence"]
    if mm > 0 and usage["in_month"] >= mm:
        return f"Your residence has reached the limit of {mm} booking{'' if mm == 1 else 's'} of {name} this month."
    return None


# ---------- Availability ----------


def availability(db: Db, area: dict, residence_id: int, start_date: str, days: int, now: str | None = None) -> list[dict]:
    now = now or local_now()
    end_date = add_days(start_date, days)
    booked = all_(
        db,
        """SELECT start_at, end_at, residence_id FROM reservations
           WHERE common_area_id = ? AND status IN ('pending', 'confirmed') AND start_at >= ? AND start_at < ?""",
        (area["id"], f"{start_date}T00:00", f"{end_date}T00:00"),
    )
    step, open_, close = area["slot_minutes"], to_minutes(area["open_time"]), to_minutes(area["close_time"])
    out = []
    for i in range(days):
        date = add_days(start_date, i)
        blackout = blackout_for(db, area["id"], date)
        restriction = booking_restriction(db, area, residence_id, date, now)
        slots = []
        m = open_
        while m + step <= close:
            s, e = f"{date}T{from_minutes(m)}", f"{date}T{from_minutes(m + step)}"
            mine = [b for b in booked if b["start_at"] < e and b["end_at"] > s]
            if s <= now:
                state = "past"
            elif mine:
                state = "booked"
            else:
                state = "free"
            slots.append({"start": from_minutes(m), "end": from_minutes(m + step), "state": state,
                          "yours": bool(mine) and all(b["residence_id"] == residence_id for b in mine)})
            m += step
        out.append({
            "date": date,
            "closed": bool(blackout), "closed_reason": blackout["reason"] if blackout else None,
            "restriction": restriction if not blackout else None,
            "bookable": restriction is None,
            "slots": slots,
        })
    return out


# ---------- Booking ----------


def _label(area: str, start_at: str) -> str:
    return f"{area} {start_at.replace('T', ' ')}"


def create_charges(db: Db, reservation_id: int, area: dict, residence_id: int, start_at: str) -> None:
    """Fee and deposit charges of a confirmed booking (idempotent per reservation/type)."""
    date = start_at[:10]
    sql = "INSERT OR IGNORE INTO charges (residence_id, type, reservation_id, description, amount_cents, due_date) VALUES (?,?,?,?,?,?)"
    if area["fee_cents"] > 0:
        db.execute(sql, (residence_id, "common_area", reservation_id, _label(area["name"], start_at), area["fee_cents"], date))
    if area["deposit_cents"] > 0:
        db.execute(sql, (residence_id, "deposit", reservation_id, f"Deposit — {_label(area['name'], start_at)}", area["deposit_cents"], date))


def create_reservation(db: Db, *, area_id: int, residence_id: int, user_id: int, date: str, start: str, note: str = "", now: str | None = None) -> dict:
    now = now or local_now()
    area = get_area(db, area_id)
    if not area or not area["active"]:
        raise DomainError("That area is not available.")
    if not is_date(date):
        raise DomainError("Invalid date.")
    try:
        start_min = to_minutes(start)
    except ValueError:
        raise DomainError("Invalid start time.")
    end_min = start_min + area["slot_minutes"]
    open_min, close_min = to_minutes(area["open_time"]), to_minutes(area["close_time"])
    if start_min < open_min or end_min > close_min or (start_min - open_min) % area["slot_minutes"] != 0:
        raise DomainError(f"Choose a {area['slot_minutes']}-minute slot between {area['open_time']} and {area['close_time']}.")
    start_at, end_at = f"{date}T{from_minutes(start_min)}", f"{date}T{from_minutes(end_min)}"
    if start_at <= now:
        raise DomainError("You can only book future slots.")

    def work() -> dict:
        restriction = booking_restriction(db, area, residence_id, date, now)
        if restriction:
            raise DomainError(restriction)
        clash = db.execute(
            "SELECT 1 FROM reservations WHERE common_area_id = ? AND status IN ('pending', 'confirmed') AND start_at < ? AND end_at > ?",
            (area_id, end_at, start_at),
        ).fetchone()
        if clash:
            raise DomainError("That slot is already booked.", 409)
        status = "pending" if area["requires_approval"] else "confirmed"
        cur = db.execute(
            "INSERT INTO reservations (common_area_id, residence_id, user_id, start_at, end_at, status, note) VALUES (?,?,?,?,?,?,?)",
            (area_id, residence_id, user_id, start_at, end_at, status, note.strip()),
        )
        rid = int(cur.lastrowid)
        if status == "confirmed":
            create_charges(db, rid, area, residence_id, start_at)
        return {"id": rid, "status": status}

    return tx(db, work)


def cancel_reservation(db: Db, reservation_id: int, *, residence_id: int, user_id: int, reason: str = "", now: str | None = None) -> None:
    """Resident cancellation: own residence only, cutoff applies. Unpaid fee/deposit charges are voided."""
    now = now or local_now()

    def work() -> None:
        r = get_reservation(db, reservation_id)
        if not r or r["residence_id"] != residence_id:
            raise NotFound("Reservation not found.")
        if r["status"] in ("cancelled", "rejected"):
            return
        ok, why = resident_can_cancel(r, now)
        if not ok:
            raise DomainError(why or "Cannot cancel.")
        db.execute("UPDATE reservations SET status = 'cancelled', cancelled_at = ?, cancelled_by = ?, cancel_reason = ? WHERE id = ?",
                   (now, user_id, reason.strip(), reservation_id))
        db.execute(
            """UPDATE charges SET status = 'void' WHERE reservation_id = ? AND status = 'pending'
               AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.charge_id = charges.id AND p.status != 'rejected')""",
            (reservation_id,),
        )

    tx(db, work)
