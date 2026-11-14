"""Admin payment review, ported from repos/payments.ts (confirm / reject / receipt). Audit rows are written in the same transaction."""
from ..audit import log_audit
from ..db import Db, all_, one, tx
from ..errors import DomainError, NotFound
from ..timeutil import local_now
from .billing import format_receipt_no

ADMIN_SELECT = """SELECT p.id, p.charge_id, p.residence_id, p.amount_cents, p.method, p.reference, p.paid_at, p.note, p.status,
  p.review_note, p.reviewed_at, p.receipt_no, p.receipt_issued_at, p.proof_name, p.proof_type, p.batch_id, p.created_at,
  c.description AS charge_description, c.amount_cents AS charge_amount_cents, c.type AS charge_type,
  r.code AS residence_code, u.name AS registered_by_name, ru.name AS reviewed_by_name
  FROM payments p
  JOIN charges c ON c.id = p.charge_id
  JOIN residences r ON r.id = p.residence_id
  JOIN users u ON u.id = p.registered_by
  LEFT JOIN users ru ON ru.id = p.reviewed_by"""


def _present(r: dict) -> dict:
    r["receipt"] = format_receipt_no(r["receipt_no"])
    r["has_proof"] = bool(r["proof_name"])
    return r


def money(cents: int) -> str:
    return f"{cents / 100:,.2f}"


def list_payments(db: Db, status: str | None = None, limit: int = 200) -> list[dict]:
    where = "WHERE p.status = ?" if status else ""
    order = "p.created_at, p.id" if status == "pending" else "p.created_at DESC, p.id DESC"  # review queue: oldest first
    params = (status, limit) if status else (limit,)
    return [_present(r) for r in all_(db, f"{ADMIN_SELECT} {where} ORDER BY {order} LIMIT ?", params)]


def get_payment(db: Db, payment_id: int) -> dict:
    row = one(db, f"{ADMIN_SELECT} WHERE p.id = ?", (payment_id,))
    if not row:
        raise NotFound("Payment not found.")
    row = _present(row)
    row["batch"] = (
        [_present(r) for r in all_(db, f"{ADMIN_SELECT} WHERE p.batch_id = ? ORDER BY p.id", (row["batch_id"],))]
        if row["batch_id"] else []
    )
    return row


def _ref(db: Db, payment_id: int) -> dict:
    row = one(
        db,
        """SELECT p.status, p.charge_id, p.amount_cents, p.receipt_no, r.code AS residence_code, c.description AS charge_description
           FROM payments p JOIN residences r ON r.id = p.residence_id JOIN charges c ON c.id = p.charge_id WHERE p.id = ?""",
        (payment_id,),
    )
    if not row:
        raise NotFound("Payment not found.")
    return row


def _issue_receipt(db: Db, payment_id: int, admin_id: int, now: str) -> int:
    p = _ref(db, payment_id)
    if p["status"] != "confirmed":
        raise DomainError("Receipts can only be issued for confirmed payments.")
    if p["receipt_no"] is not None:
        return p["receipt_no"]
    nxt = db.execute("SELECT COALESCE(MAX(receipt_no), 0) + 1 FROM payments").fetchone()[0]
    db.execute("UPDATE payments SET receipt_no = ?, receipt_issued_at = ? WHERE id = ?", (nxt, now, payment_id))
    log_audit(
        db, actor_id=admin_id, action="payment.receipt", entity_type="payment", entity_id=payment_id, entity_label=p["residence_code"],
        summary=f"Issued receipt {format_receipt_no(nxt)} for {money(p['amount_cents'])} — {p['residence_code']}",
        details={"receiptNo": nxt, "amount": p["amount_cents"]}, at=f"{now}:00",
    )
    return nxt


def confirm_payment(db: Db, payment_id: int, admin_id: int, now: str | None = None) -> dict:
    """Confirms a pending payment; the charge flips to paid once confirmed payments cover it. Issues the receipt."""
    now = now or local_now()

    def work() -> dict:
        p = _ref(db, payment_id)
        if p["status"] != "pending":
            raise DomainError("This payment has already been reviewed.", 409)
        db.execute("UPDATE payments SET status = 'confirmed', reviewed_by = ?, reviewed_at = ? WHERE id = ?", (admin_id, now, payment_id))
        settled = db.execute(
            """UPDATE charges SET status = 'paid' WHERE id = ? AND status = 'pending'
               AND amount_cents <= (SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE charge_id = ? AND status = 'confirmed')""",
            (p["charge_id"], p["charge_id"]),
        ).rowcount > 0
        log_audit(
            db, actor_id=admin_id, action="payment.confirm", entity_type="payment", entity_id=payment_id, entity_label=p["residence_code"],
            summary=f"Confirmed {money(p['amount_cents'])} for {p['charge_description']} — {p['residence_code']}{' (charge settled)' if settled else ''}",
            details={"chargeId": p["charge_id"], "amount": p["amount_cents"], "chargeSettled": settled}, at=f"{now}:00",
        )
        receipt_no = _issue_receipt(db, payment_id, admin_id, now)
        return {"id": payment_id, "status": "confirmed", "charge_settled": settled, "receipt_no": receipt_no, "receipt": format_receipt_no(receipt_no)}

    return tx(db, work)


def reject_payment(db: Db, payment_id: int, admin_id: int, reason: str, now: str | None = None) -> dict:
    """Rejects a pending payment with a reason; the amount becomes payable again."""
    now = now or local_now()
    reason = reason.strip()
    if not reason:
        raise DomainError("Give the resident a reason for rejecting the payment.")

    def work() -> dict:
        p = _ref(db, payment_id)
        if p["status"] != "pending":
            raise DomainError("This payment has already been reviewed.", 409)
        db.execute("UPDATE payments SET status = 'rejected', reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
                   (admin_id, now, reason, payment_id))
        log_audit(
            db, actor_id=admin_id, action="payment.reject", severity="warning", entity_type="payment", entity_id=payment_id,
            entity_label=p["residence_code"],
            summary=f"Rejected {money(p['amount_cents'])} for {p['charge_description']} — {p['residence_code']}: {reason}",
            details={"chargeId": p["charge_id"], "amount": p["amount_cents"], "reason": reason}, at=f"{now}:00",
        )
        return {"id": payment_id, "status": "rejected"}

    return tx(db, work)
