API = "/api/v1/admin"


def add_payment(raw, amount, charge=1, residence=1, user=3):
    cur = raw.execute("INSERT INTO payments (charge_id, residence_id, registered_by, amount_cents, method, paid_at) VALUES (?,?,?,?,'transfer','2026-11-01')",
                      (charge, residence, user, amount))
    raw.commit()
    return cur.lastrowid


def test_dashboard(client, admin, raw):
    d = client.get(f"{API}/dashboard", headers=admin).json()
    assert d["counts"]["active_residences"] == 2 and d["counts"]["active_residents"] == 2
    assert d["finance"]["outstanding_cents"] == 15000
    assert d["counts"]["payments_to_review"] == 0 and d["counts"]["reservations_to_approve"] == 0
    add_payment(raw, 5000)
    d = client.get(f"{API}/dashboard", headers=admin).json()
    assert d["counts"]["payments_to_review"] == 1 and d["finance"]["review_cents"] == 5000
    assert d["recent_payments"][0]["residence_code"] == "A-101"


def test_full_payment_confirm_settles_charge_and_issues_receipt(client, admin, raw):
    pid = add_payment(raw, 15000)
    queue = client.get(f"{API}/payments?status=pending", headers=admin).json()
    assert [p["id"] for p in queue] == [pid] and queue[0]["residence_code"] == "A-101"
    r = client.post(f"{API}/payments/{pid}/confirm", headers=admin)
    assert r.status_code == 200 and r.json()["charge_settled"] is True and r.json()["receipt"] == "R-00001"
    assert raw.execute("SELECT status FROM charges WHERE id = 1").fetchone()[0] == "paid"
    actions = [a[0] for a in raw.execute("SELECT action FROM audit_log WHERE category = 'payment' ORDER BY id")]
    assert actions == ["payment.confirm", "payment.receipt"]
    assert client.post(f"{API}/payments/{pid}/confirm", headers=admin).status_code == 409  # already reviewed


def test_partial_payment_does_not_settle_and_receipts_are_sequential(client, admin, raw):
    a, b = add_payment(raw, 5000), add_payment(raw, 10000)
    assert client.post(f"{API}/payments/{a}/confirm", headers=admin).json()["charge_settled"] is False
    assert raw.execute("SELECT status FROM charges WHERE id = 1").fetchone()[0] == "pending"
    r = client.post(f"{API}/payments/{b}/confirm", headers=admin).json()
    assert r["charge_settled"] is True and r["receipt"] == "R-00002"


def test_reject_needs_reason_and_frees_amount(client, admin, resident, raw):
    pid = add_payment(raw, 15000)
    assert client.post(f"{API}/payments/{pid}/reject", headers=admin, json={"reason": "  "}).status_code in (400, 422)
    assert client.post(f"{API}/payments/{pid}/reject", headers=admin, json={}).status_code == 422
    r = client.post(f"{API}/payments/{pid}/reject", headers=admin, json={"reason": "Proof unreadable"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.get(f"/api/v1/resident/dashboard", headers=resident).json()["balance"]["balance_cents"] == 15000
    row = raw.execute("SELECT severity, summary FROM audit_log WHERE action = 'payment.reject'").fetchone()
    assert row["severity"] == "warning" and "Proof unreadable" in row["summary"]
    assert client.post(f"{API}/payments/{pid}/reject", headers=admin, json={"reason": "again"}).status_code == 409


def test_detail_shows_batch_and_unknown_is_404(client, admin, raw):
    a = add_payment(raw, 5000)
    b = add_payment(raw, 5000)
    raw.execute("UPDATE payments SET batch_id = 'abc' WHERE id IN (?,?)", (a, b)); raw.commit()
    d = client.get(f"{API}/payments/{a}", headers=admin).json()
    assert len(d["batch"]) == 2
    assert client.get(f"{API}/payments/9999", headers=admin).status_code == 404
    assert client.post(f"{API}/payments/9999/confirm", headers=admin).status_code == 404


def test_residents_cannot_review(client, resident, raw):
    pid = add_payment(raw, 5000)
    assert client.post(f"{API}/payments/{pid}/confirm", headers=resident).status_code == 403
    assert client.get(f"{API}/payments", headers=resident).status_code == 403
