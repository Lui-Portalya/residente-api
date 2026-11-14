"""Dashboard summaries for admins and residents."""
from ..db import Db, all_, one
from ..timeutil import local_now, today
from . import billing, reservations

OPEN_CHARGES = """SELECT c.id, c.residence_id, c.amount_cents, c.due_date,
    COALESCE((SELECT SUM(p.amount_cents) FROM payments p WHERE p.charge_id = c.id AND p.status = 'confirmed'), 0) AS confirmed_cents,
    COALESCE((SELECT SUM(p.amount_cents) FROM payments p WHERE p.charge_id = c.id AND p.status = 'pending'), 0) AS review_cents
  FROM charges c WHERE c.status = 'pending'"""


def finance_summary(db: Db, as_of: str | None = None) -> dict:
    """Outstanding = charge amount minus confirmed payments; overdue = the outstanding part past its due date (reports.ts)."""
    as_of = as_of or today()
    rows = all_(
        db,
        f"""WITH open AS ({OPEN_CHARGES})
            SELECT r.id,
              COUNT(o.id) AS open_charges,
              COALESCE(SUM(o.amount_cents - o.confirmed_cents), 0) AS outstanding,
              COALESCE(SUM(o.review_cents), 0) AS review,
              COALESCE(SUM(CASE WHEN o.due_date < ? THEN o.amount_cents - o.confirmed_cents ELSE 0 END), 0) AS overdue
            FROM residences r LEFT JOIN open o ON o.residence_id = r.id
            GROUP BY r.id HAVING r.active = 1 OR COUNT(o.id) > 0""",
        (as_of,),
    )
    out = {"outstanding_cents": 0, "overdue_cents": 0, "review_cents": 0, "residences": {"up_to_date": 0, "pending": 0, "overdue": 0}}
    for r in rows:
        out["outstanding_cents"] += r["outstanding"]
        out["overdue_cents"] += r["overdue"]
        out["review_cents"] += r["review"]
        out["residences"]["overdue" if r["overdue"] > 0 else "pending" if r["outstanding"] > 0 else "up_to_date"] += 1
    return out


def admin_dashboard(db: Db) -> dict:
    now = local_now()
    count = lambda sql: db.execute(sql).fetchone()[0]  # noqa: E731
    upcoming = all_(
        db,
        f"{reservations.SELECT} WHERE v.status IN ('pending', 'confirmed') AND v.end_at > ? ORDER BY v.start_at LIMIT 10",
        (now,),
    )
    recent = all_(
        db,
        """SELECT p.id, r.code AS residence_code, c.description AS charge_description, p.amount_cents, p.method, p.status, p.paid_at
           FROM payments p JOIN residences r ON r.id = p.residence_id JOIN charges c ON c.id = p.charge_id
           ORDER BY p.created_at DESC, p.id DESC LIMIT 5""",
    )
    return {
        "as_of": now,
        "counts": {
            "active_residences": count("SELECT COUNT(*) FROM residences WHERE active = 1"),
            "active_residents": count("SELECT COUNT(*) FROM users WHERE role = 'resident' AND active = 1"),
            "payments_to_review": count("SELECT COUNT(*) FROM payments WHERE status = 'pending'"),
            "reservations_to_approve": count("SELECT COUNT(*) FROM reservations WHERE status = 'pending'"),
        },
        "finance": finance_summary(db),
        "upcoming_reservations": [
            {"id": r["id"], "area_name": r["area_name"], "residence_code": r["residence_code"], "user_name": r["user_name"],
             "start_at": r["start_at"], "end_at": r["end_at"], "status": r["status"]} for r in upcoming
        ],
        "recent_payments": recent,
    }


def resident_dashboard(db: Db, user: dict) -> dict:
    now = local_now()
    rid = user["residence"]["id"]
    pending = billing.list_charges(db, rid, "pending")
    next_bookings = reservations.list_upcoming(db, rid, now, limit=5)
    return {
        "as_of": now,
        "user": {"id": user["id"], "name": user["name"], "email": user["email"]},
        "residence": user["residence"],
        "balance": {
            "balance_cents": sum(c["remaining_cents"] for c in pending),
            "open_charges": len(pending),
            "overdue_charges": sum(1 for c in pending if c["overdue"]),
            "overdue_cents": sum(c["remaining_cents"] for c in pending if c["overdue"]),
            "under_review_cents": one(
                db,
                "SELECT COALESCE(SUM(amount_cents), 0) AS n FROM payments WHERE residence_id = ? AND status = 'pending'", (rid,),
            )["n"],  # type: ignore[index]
        },
        "pending_charges": pending,
        "recent_payments": billing.list_payments(db, rid, limit=5),
        "next_bookings": [reservations.present(r, now) for r in next_bookings],
    }
