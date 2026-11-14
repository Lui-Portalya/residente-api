from .conftest import area_id, days_ahead

API = "/api/v1/resident"


def book(client, h, aid, date, start, note=""):
    return client.post(f"{API}/reservations", headers=h, json={"area_id": aid, "date": date, "start": start, "note": note})


def test_dashboard_shows_balance_and_charge(client, resident):
    d = client.get(f"{API}/dashboard", headers=resident).json()
    assert d["residence"]["code"] == "A-101"
    assert d["balance"]["balance_cents"] == 15000 and d["balance"]["open_charges"] == 1
    assert d["pending_charges"][0]["type"] == "maintenance"


def test_charges_and_payments_lists(client, resident, raw):
    assert len(client.get(f"{API}/charges", headers=resident).json()) == 1
    assert client.get(f"{API}/charges?status=paid", headers=resident).json() == []
    assert client.get(f"{API}/payments", headers=resident).json() == []
    raw.execute("INSERT INTO payments (charge_id, residence_id, registered_by, amount_cents, method, paid_at) VALUES (1,1,3,5000,'cash','2026-11-01')")
    raw.commit()
    p = client.get(f"{API}/payments", headers=resident).json()
    assert p[0]["status"] == "pending" and p[0]["receipt"] is None
    assert client.get(f"{API}/dashboard", headers=resident).json()["balance"]["balance_cents"] == 10000


def test_other_residence_sees_nothing_of_ours(client, neighbour):
    assert client.get(f"{API}/charges", headers=neighbour).json() == []


def test_areas_and_availability(client, resident, raw):
    areas = client.get(f"{API}/areas", headers=resident).json()
    assert {a["name"] for a in areas} == {"Pool", "Party Room", "Tennis Court"}
    pool = area_id(raw, "Pool")
    days = client.get(f"{API}/areas/{pool}/availability?from={days_ahead(1)}&days=2", headers=resident).json()["days"]
    assert len(days) == 2 and len(days[0]["slots"]) == 12 and all(s["state"] == "free" for s in days[0]["slots"])


def test_book_free_area_confirms_and_creates_fee_charge(client, resident, raw):
    tennis = area_id(raw, "Tennis Court")
    r = book(client, resident, tennis, days_ahead(3), "09:00")
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["status"] == "confirmed" and b["fee"]["amount_cents"] == 1000
    slots = client.get(f"{API}/areas/{tennis}/availability?from={days_ahead(3)}&days=1", headers=resident).json()["days"][0]["slots"]
    s = next(s for s in slots if s["start"] == "09:00")
    assert s["state"] == "booked" and s["yours"] is True


def test_clash_and_slot_validation(client, resident, neighbour, raw):
    pool = area_id(raw, "Pool")
    assert book(client, resident, pool, days_ahead(2), "10:00").status_code == 201
    assert book(client, neighbour, pool, days_ahead(2), "10:00").status_code == 409
    assert book(client, resident, pool, days_ahead(2), "10:30").status_code == 400  # not aligned
    assert book(client, resident, pool, days_ahead(2), "20:00").status_code == 400  # after closing
    assert book(client, resident, pool, "2020-01-01", "10:00").status_code == 400  # past
    assert book(client, resident, 999, days_ahead(2), "10:00").status_code == 400
    assert book(client, resident, pool, "not-a-date", "10:00").status_code == 400


def test_party_room_needs_approval_and_has_no_charges_yet(client, resident, raw):
    room = area_id(raw, "Party Room")
    r = book(client, resident, room, days_ahead(10), "12:00", "Birthday")
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["fee"] is None
    assert raw.execute("SELECT COUNT(*) FROM charges WHERE reservation_id IS NOT NULL").fetchone()[0] == 0
    # a pending request can always be withdrawn
    c = client.post(f"{API}/reservations/{r.json()['id']}/cancel", headers=resident, json={"reason": "changed plans"})
    assert c.status_code == 200 and c.json()["status"] == "cancelled"


def test_limits_per_residence_and_advance_days(client, resident, raw):
    tennis = area_id(raw, "Tennis Court")  # max 2 active, 14 days ahead
    assert book(client, resident, tennis, days_ahead(2), "09:00").status_code == 201
    assert book(client, resident, tennis, days_ahead(2), "10:00").status_code == 201
    third = book(client, resident, tennis, days_ahead(2), "11:00")
    assert third.status_code == 400 and "limit 2" in third.json()["detail"]
    assert "ahead" in book(client, resident, tennis, days_ahead(30), "09:00").json()["detail"]


def test_blackout_blocks_booking(client, resident, raw):
    pool = area_id(raw, "Pool")
    raw.execute("INSERT INTO area_blackouts (common_area_id, start_date, end_date, reason, created_by) VALUES (NULL, ?, ?, 'Maintenance', 1)",
                (days_ahead(4), days_ahead(5)))
    raw.commit()
    r = book(client, resident, pool, days_ahead(4), "10:00")
    assert r.status_code == 400 and "Maintenance" in r.json()["detail"]
    day = client.get(f"{API}/areas/{pool}/availability?from={days_ahead(4)}&days=1", headers=resident).json()["days"][0]
    assert day["closed"] and day["closed_reason"] == "Maintenance"


def test_cancel_rules_and_scoping(client, resident, neighbour, raw):
    tennis = area_id(raw, "Tennis Court")  # 24h cutoff
    far = book(client, resident, tennis, days_ahead(5), "09:00").json()["id"]
    c = client.post(f"{API}/reservations/{far}/cancel", headers=resident)
    assert c.status_code == 200 and c.json()["status"] == "cancelled"
    assert raw.execute("SELECT status FROM charges WHERE reservation_id = ?", (far,)).fetchone()[0] == "void"
    assert client.post(f"{API}/reservations/{far}/cancel", headers=resident).status_code == 200  # idempotent
    # someone else's booking reads as not found
    other = book(client, resident, tennis, days_ahead(6), "09:00").json()["id"]
    assert client.post(f"{API}/reservations/{other}/cancel", headers=neighbour).status_code == 404
    # inside the cutoff window
    soon = book(client, resident, area_id(raw, "Pool"), days_ahead(0), "23:00")  # outside hours, ignored
    assert soon.status_code == 400
    raw.execute("INSERT INTO reservations (common_area_id, residence_id, user_id, start_at, end_at, status) "
                "VALUES (?,1,3,?,?, 'confirmed')", (tennis, f"{days_ahead(1)}T00:05", f"{days_ahead(1)}T01:05"))
    raw.commit()
    rid = raw.execute("SELECT MAX(id) FROM reservations").fetchone()[0]
    blocked = client.post(f"{API}/reservations/{rid}/cancel", headers=resident)
    assert blocked.status_code == 400 and "Cancellations close" in blocked.json()["detail"]


def test_reservation_lists(client, resident, raw):
    tennis = area_id(raw, "Tennis Court")
    rid = book(client, resident, tennis, days_ahead(3), "09:00").json()["id"]
    up = client.get(f"{API}/reservations", headers=resident).json()
    assert [r["id"] for r in up] == [rid] and up[0]["can_cancel"] is True
    client.post(f"{API}/reservations/{rid}/cancel", headers=resident)
    assert client.get(f"{API}/reservations", headers=resident).json() == []
    hist = client.get(f"{API}/reservations?scope=history", headers=resident).json()
    assert [r["status"] for r in hist] == ["cancelled"]
    assert len(client.get(f"{API}/dashboard", headers=resident).json()["next_bookings"]) == 0
