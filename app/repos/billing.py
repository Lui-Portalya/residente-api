"""A residence's charges and payments (read side), ported from repos/payments.ts."""
from ..db import Db, all_
from ..timeutil import today

CHARGE_SELECT = """SELECT c.id, c.type, c.description, c.amount_cents, c.due_date, c.status, c.period, c.reservation_id,
  COALESCE((SELECT SUM(p.amount_cents) FROM payments p WHERE p.charge_id = c.id AND p.status != 'rejected'), 0) AS paid_cents,
  COALESCE((SELECT SUM(p.amount_cents) FROM payments p WHERE p.charge_id = c.id AND p.status = 'confirmed'), 0) AS confirmed_cents
  FROM charges c"""


def list_charges(db: Db, residence_id: int, status: str | None = None) -> list[dict]:
    cond = "AND c.status = ?" if status else "AND c.status != 'void'"
    params = (residence_id, status) if status else (residence_id,)
    rows = all_(db, f"{CHARGE_SELECT} WHERE c.residence_id = ? {cond} ORDER BY c.due_date DESC, c.id DESC", params)
    t = today()
    for r in rows:
        r["remaining_cents"] = max(r["amount_cents"] - r["paid_cents"], 0) if r["status"] == "pending" else 0
        # Overdue once the due date has passed (still payable on the due day itself).
        r["overdue"] = r["status"] == "pending" and r["due_date"] < t
    return rows


def balance_cents(db: Db, residence_id: int) -> int:
    """What the residence still has to register (submitted payments count, even while awaiting confirmation)."""
    return sum(c["remaining_cents"] for c in list_charges(db, residence_id, "pending"))


def format_receipt_no(n: int | None) -> str | None:
    return None if n is None else f"R-{n:05d}"


def list_payments(db: Db, residence_id: int, limit: int = 50) -> list[dict]:
    rows = all_(
        db,
        """SELECT p.id, p.charge_id, c.description AS charge_description, p.amount_cents, p.method, p.reference, p.paid_at,
                  p.status, p.review_note, p.receipt_no, p.proof_name, p.batch_id, p.created_at
           FROM payments p JOIN charges c ON c.id = p.charge_id WHERE p.residence_id = ?
           ORDER BY p.paid_at DESC, p.id DESC LIMIT ?""",
        (residence_id, limit),
    )
    for r in rows:
        r["receipt"] = format_receipt_no(r["receipt_no"])
        r["has_proof"] = bool(r.pop("proof_name"))
    return rows
